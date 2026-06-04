"""Source météo Open-Meteo *Single Runs* — runs explicites et déterministes.

Cf. **ADR-0011**. Contrairement à l'API *Forecast* (``openmeteo.py``), qui
assemble en silence les premières heures de runs successifs, la **Single Runs
API** (``https://single-runs-api.open-meteo.com/v1/forecast``) renvoie **la
série d'un run précis** (``&run=<ISO sans secondes>``), de son init T+0 vers
l'avant. On peut donc **étiqueter honnêtement le run utilisé** et distinguer
analyse (T+0) et prévision (T+h).

Principes (ADR-0011, cf. mémoire ``feedback_runs_deterministes_utc``) :

- **Déterministe, zéro itération** : le run de chaque modèle est donné par une
  table créneau→run figée (``runs_du_creneau``), jamais par un probe/cascade.
  Si un run manque systématiquement à l'heure dite, on corrige la constante,
  pas une logique de secours runtime.
- **Tout en UTC**, aligné sur les cycles 00/06/12/18 Z.
- **Provenance exacte** : la fusion App 1 garde la trace du run réellement
  servi par modèle (``ResultatPrevision.runs_utilises``).
- **Pas de repli** : si un run est muet, on **omet** sa contribution (le reste
  part) ; aucun retour vers l'API Forecast.

Faits vérifiés le 2026-06-04 (sonde) repris ici :

- AROME France HD **ne fournit ni rayonnement ni proba** → fusion obligatoire
  (AROME cœur, ARPEGE comble le rayonnement, ECMWF comble la proba).
- Le rayonnement reste ``shortwave_radiation`` (``shortwave_radiation_ghi``
  n'existe pas).
- La proba route en interne vers ``ecmwf_ifs025_ensemble`` (dispo distincte,
  souvent en retard) → maillon le plus susceptible d'être omis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd
import requests

from ._http_retry import get_avec_retry
from .openmeteo import appliquer_conventions_socle

logger = logging.getLogger(__name__)

SINGLE_RUNS_URL = "https://single-runs-api.open-meteo.com/v1/forecast"

# Bornes UTC des créneaux (= heures de cron App 1). En vigueur dès ces
# heures ; entre minuit et le créneau du matin, on garde l'après-midi de la
# veille (cf. ``creneau_run``). Cf. ADR-0011 D3.
HEURE_CRENEAU_MATIN = 5.5  # 05:30 UTC
HEURE_CRENEAU_APREM = 17.5  # 17:30 UTC

CYCLE_RUN_H = 6

# Identifiants de modèles Open-Meteo.
AROME = "meteofrance_arome_france_hd"
ARPEGE = "meteofrance_arpege_europe"
# ``ECMWF`` sert à la fois d'identifiant de modèle (``ecmwf_ifs025``, qui route
# vers l'ensemble quand on demande la proba) ET de clé du run **ENS court**
# (proba App 1, 18Z J-1 / 06Z J — l'horizon 48 h suffit).
ECMWF = "ecmwf_ifs025"
# 2e run ECMWF, clé distincte : déterministe **HRES long** (tendance App 2).
# Même modèle, mais il faut un run 00/12Z (qui seuls atteignent ~240 h ; les
# runs 06/18Z plafonnent à ~90 h) → le dernier 00/12Z publié au créneau
# (12Z J-1 le matin, 00Z J l'après-midi). Cf. ADR-0011 D3.
ECMWF_HRES = "ecmwf_hres"

# Variables Open-Meteo (noms natifs) par usage.
# Le cœur vient d'AROME ; ARPEGE comble le rayonnement (et la queue 48-72 h
# qu'AROME ne couvre pas) ; ECMWF-ENS n'apporte que la proba (isolée pour que
# la fragilité de l'ensemble n'entraîne pas le reste).
_VARS_COEUR = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
    "weather_code",
    "cloud_cover",
)
VARS_AROME: tuple[str, ...] = _VARS_COEUR
VARS_ARPEGE: tuple[str, ...] = (*_VARS_COEUR, "shortwave_radiation")
VARS_ECMWF: tuple[str, ...] = ("precipitation_probability",)
# Séries mono-modèle App 2 (ARPEGE court, ECMWF-HRES long) : cœur + rayonnement
# (ni l'un ni l'autre ne fournit la proba — elle vient de la fusion AROME/ENS).
VARS_MONO_MODELE: tuple[str, ...] = (*_VARS_COEUR, "shortwave_radiation")


class PrevisionIndisponibleError(RuntimeError):
    """Aucun run exploitable (même le cœur AROME manque) — le mail n'a pas de prévision."""


def creneau_run(now_utc: pd.Timestamp) -> tuple[str, pd.Timestamp]:
    """Créneau courant et jour de référence J, selon les bornes UTC fixes.

    Renvoie ``(créneau, jour)`` où ``créneau`` ∈ {``"matin"``,
    ``"apres-midi"``} et ``jour`` est le 00:00 UTC de J (tz-aware UTC). Entre
    minuit et 05:30 UTC, on reste sur le créneau **après-midi de la veille**
    (pas de run nocturne auquel on ne fait pas encore confiance). Cf. ADR-0011
    D3.
    """
    h = now_utc.hour + now_utc.minute / 60.0
    jour = now_utc.tz_convert("UTC").normalize()
    if h < HEURE_CRENEAU_MATIN:
        return "apres-midi", jour - pd.Timedelta(days=1)
    if h < HEURE_CRENEAU_APREM:
        return "matin", jour
    return "apres-midi", jour


def runs_du_creneau(creneau: str, jour: pd.Timestamp) -> dict[str, pd.Timestamp]:
    """Table créneau→run (ADR-0011 D3). ``jour`` = 00:00 UTC de J.

    Clés : ``AROME``, ``ARPEGE``, ``ECMWF`` (run ENS court, proba App 1),
    ``ECMWF_HRES`` (déterministe long, tendance App 2).

    - **matin** : AROME/ARPEGE 00Z J ; ECMWF 18Z J-1 ; ECMWF_HRES 12Z J-1.
    - **après-midi** : AROME/ARPEGE 12Z J ; ECMWF 06Z J ; ECMWF_HRES 00Z J.

    Règle : Météo-France sur le run de la demi-journée courante ; ECMWF-ENS un
    cran (6 h) derrière ; ECMWF-HRES = dernier run long (00/12Z) publié. Runs
    renvoyés tz-aware UTC.
    """
    if creneau == "matin":
        mf = jour
        ens = jour - pd.Timedelta(hours=CYCLE_RUN_H)  # 18Z J-1
        hres = jour - pd.Timedelta(hours=12)  # 12Z J-1
    elif creneau == "apres-midi":
        mf = jour + pd.Timedelta(hours=12)
        ens = jour + pd.Timedelta(hours=CYCLE_RUN_H)  # 06Z J
        hres = jour  # 00Z J
    else:  # pragma: no cover - garde-fou
        raise ValueError(f"Créneau inconnu : {creneau!r}")
    return {AROME: mf, ARPEGE: mf, ECMWF: ens, ECMWF_HRES: hres}


def creneaux_precedents(now_utc: pd.Timestamp, n: int) -> list[tuple[str, pd.Timestamp]]:
    """Les ``n`` créneaux précédant le créneau courant, du plus récent au plus ancien.

    Les créneaux avancent par pas de 12 h (matin ↔ après-midi). Sert au stitch
    déterministe du passé de l'App 2 (ADR-0011 D6) : chaque créneau-run
    précédent fournit son segment de 12 h. Ex. depuis (matin, J) :
    [(apres-midi, J-1), (matin, J-1), (apres-midi, J-2), (matin, J-2)].
    """
    creneau, jour = creneau_run(now_utc)
    out: list[tuple[str, pd.Timestamp]] = []
    for _ in range(n):
        if creneau == "matin":
            creneau, jour = "apres-midi", jour - pd.Timedelta(days=1)
        else:
            creneau, jour = "matin", jour
        out.append((creneau, jour))
    return out


def ancre_creneau(now_utc: pd.Timestamp) -> pd.Timestamp:
    """Init du run-cœur (AROME) du créneau courant = ancre de fenêtre UTC.

    C'est le 00Z (matin) ou 12Z (après-midi) de J. Sert d'ancre d'affichage
    (fenêtre `[ancre ; ancre+48 h]`) et de borne des bins de période UTC
    (0-6/6-12/12-18/18-24). Cf. ADR-0011 D5.
    """
    creneau, jour = creneau_run(now_utc)
    return runs_du_creneau(creneau, jour)[AROME]


def fusionner_priorite(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Fusionne N DataFrames par priorité décroissante (ordre de la liste).

    Pour chaque cellule, la valeur du 1er DataFrame disponible (non-NaN) est
    retenue ; les suivants ne comblent que les trous (``combine_first`` en
    cascade). Remplace l'ancien ``_fusionner_modeles`` sur colonnes suffixées :
    en Single Runs chaque modèle est un appel séparé → DataFrames distincts à
    colonnes déjà au nom socle.
    """
    if not frames:
        raise ValueError("fusionner_priorite : aucune frame")
    resultat = frames[0]
    for autre in frames[1:]:
        resultat = resultat.combine_first(autre)
    # Coercition float : une colonne tout-NaN (object) casserait les ufuncs
    # numpy aval (cf. _fusionner_modeles legacy).
    for col in resultat.columns:
        resultat[col] = pd.to_numeric(resultat[col], errors="coerce")
    return resultat.sort_index()


@dataclass
class ResultatPrevision:
    """Prévision fusionnée + provenance exacte des runs (ADR-0011 D5/D7)."""

    df: pd.DataFrame
    creneau: str
    jour: pd.Timestamp
    runs_demandes: dict[str, pd.Timestamp]
    # Runs effectivement servis (sous-ensemble de runs_demandes : un modèle
    # dont le run était muet est absent — sa contribution a été omise, D8).
    runs_utilises: dict[str, pd.Timestamp] = field(default_factory=dict)

    @property
    def ancre_utc(self) -> pd.Timestamp:
        """Init du run-cœur (AROME) = ancre de fenêtre UTC."""
        return self.runs_demandes[AROME]


# Un créneau-run précédent fournit 12 h de passé (créneaux espacés de 12 h, D6).
SEGMENT_PASSE_H = 12


@dataclass
class SerieAvecPasse:
    """Série mono-modèle [passé stitché ; prévision] + provenance (ADR-0011 D6).

    ``pivot_utc`` = init du run courant = frontière analyse-approchée / prévision.
    ``run_courant`` décrit la partie future ; ``runs_passe`` liste les runs
    explicites qui pavent le passé (du plus récent au plus ancien). Le passé est
    fait de runs explicites, pas de ``past_days`` — provenance exacte partout.
    """

    df: pd.DataFrame
    run_courant: pd.Timestamp
    runs_passe: list[pd.Timestamp] = field(default_factory=list)

    @property
    def pivot_utc(self) -> pd.Timestamp:
        return self.run_courant


@dataclass
class OpenMeteoSingleRuns:
    """Client *Single Runs* pour la prévision fusionnée App 1.

    Parameters
    ----------
    session :
        Session HTTP réutilisable (injecter un mock dans les tests).
    timeout :
        Timeout par requête (s).
    """

    session: requests.Session = field(default_factory=requests.Session)
    timeout: float = 30.0

    def obtenir_run(
        self,
        modele: str,
        run_utc: pd.Timestamp,
        latitude: float,
        longitude: float,
        horizon_jours: int,
        variables: tuple[str, ...],
    ) -> pd.DataFrame | None:
        """Récupère **un** run d'**un** modèle. ``None`` si le run est muet.

        Un run absent (HTTP 400 « run not available », réseau, payload sans
        ``hourly``) renvoie ``None`` → l'appelant **omet** cette contribution
        (D8), sans repli.
        """
        params = {
            "latitude": f"{latitude}",
            "longitude": f"{longitude}",
            "run": run_utc.strftime("%Y-%m-%dT%H:%M"),
            "models": modele,
            "hourly": ",".join(variables),
            "forecast_days": str(horizon_jours),
            "timezone": "UTC",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
        }
        try:
            response = get_avec_retry(
                self.session, SINGLE_RUNS_URL, params=params, timeout=self.timeout
            )
        except requests.HTTPError as e:
            logger.warning("Run %s muet pour %s (omis) : %s", run_utc, modele, e)
            return None
        payload = response.json()
        hourly = payload.get("hourly") if isinstance(payload, dict) else None
        if not hourly or "time" not in hourly or not hourly["time"]:
            logger.warning("Run %s sans données pour %s (omis)", run_utc, modele)
            return None
        df = pd.DataFrame(hourly)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
        return appliquer_conventions_socle(df)

    def obtenir_prevision(
        self,
        latitude: float,
        longitude: float,
        horizon_jours: int,
        now_utc: pd.Timestamp,
    ) -> ResultatPrevision:
        """Prévision App 1 fusionnée pour le créneau courant.

        Fetch déterministe d'un run par modèle (table D3), fusion par priorité
        AROME → ARPEGE (rayonnement + queue) → ECMWF (proba). Une contribution
        manquante est omise. Lève ``PrevisionIndisponibleError`` si même le cœur
        AROME manque.
        """
        creneau, jour = creneau_run(now_utc)
        runs = runs_du_creneau(creneau, jour)

        # Priorité décroissante : AROME (cœur) puis ARPEGE (rayonnement) puis
        # ECMWF-ENS (proba, run court 18Z J-1 / 06Z J = clé ``ECMWF``).
        specs = (
            (AROME, runs[AROME], VARS_AROME),
            (ARPEGE, runs[ARPEGE], VARS_ARPEGE),
            (ECMWF, runs[ECMWF], VARS_ECMWF),
        )
        frames: list[pd.DataFrame] = []
        runs_utilises: dict[str, pd.Timestamp] = {}
        for modele, run, variables in specs:
            df = self.obtenir_run(modele, run, latitude, longitude, horizon_jours, variables)
            if df is not None and not df.empty:
                frames.append(df)
                runs_utilises[modele] = run

        if not frames:
            raise PrevisionIndisponibleError(
                f"Aucun run disponible pour le créneau {creneau} {jour.date()} (cœur AROME inclus)."
            )

        fusion = fusionner_priorite(frames)
        return ResultatPrevision(
            df=fusion,
            creneau=creneau,
            jour=jour,
            runs_demandes=runs,
            runs_utilises=runs_utilises,
        )

    def obtenir_serie_avec_passe(
        self,
        modele: str,
        cle_run: str,
        latitude: float,
        longitude: float,
        horizon_jours: int,
        now_utc: pd.Timestamp,
        variables: tuple[str, ...],
        n_jours_passe: int = 2,
    ) -> SerieAvecPasse:
        """Série mono-modèle = passé stitché (runs explicites) + prévision (D6).

        Le futur vient du run courant du créneau (``cle_run`` ∈ {``ARPEGE``,
        ``ECMWF``} dans la table D3). Le passé est pavé par les
        ``n_jours_passe * 2`` créneaux-runs précédents, chacun tranché sur son
        segment de 12 h (T+0 → T+12 h) — pas de ``past_days``, provenance exacte.
        Un segment passé muet est sauté (trou possible). Lève
        ``PrevisionIndisponibleError`` si le run courant est muet.
        """
        creneau, jour = creneau_run(now_utc)
        run_courant = runs_du_creneau(creneau, jour)[cle_run]

        df_futur = self.obtenir_run(
            modele, run_courant, latitude, longitude, horizon_jours, variables
        )
        if df_futur is None or df_futur.empty:
            raise PrevisionIndisponibleError(
                f"Run courant {run_courant} muet pour {modele} (créneau {creneau})."
            )

        frames: list[pd.DataFrame] = [df_futur]
        runs_passe: list[pd.Timestamp] = []
        seg = pd.Timedelta(hours=SEGMENT_PASSE_H)
        for c, j in creneaux_precedents(now_utc, n_jours_passe * 2):
            run = runs_du_creneau(c, j)[cle_run]
            df = self.obtenir_run(modele, run, latitude, longitude, 1, variables)
            if df is None or df.empty:
                continue
            segment = df.loc[(df.index >= run) & (df.index < run + seg)]
            if not segment.empty:
                frames.append(segment)
                runs_passe.append(run)

        # Le run courant (frames[0]) est prioritaire à la frontière ; les
        # segments passés sont strictement avant son init (pas de recouvrement),
        # mais on dédoublonne par sécurité.
        serie = pd.concat(frames)
        serie = serie[~serie.index.duplicated(keep="first")].sort_index()
        for col in serie.columns:
            serie[col] = pd.to_numeric(serie[col], errors="coerce")
        return SerieAvecPasse(df=serie, run_courant=run_courant, runs_passe=runs_passe)
