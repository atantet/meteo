"""ARPEGE 0,25° **direct** depuis Météo-France Données Publiques (WCS), au point.

Alternative à Open-Meteo Single Runs, dont l'ingestion des runs s'est révélée
erratique (trous sur des runs récents). Le webservice WCS de MF (portail Données
Publiques) sert **tous** les runs sans trou et reste joignable depuis les runners
GitHub (diagnostic 2026-06-11 ; cf. `webservice.meteofrance.com` lui bloqué).

Auth : OAuth2 ``client_credentials`` — l'identifiant Basic ``METEOFRANCE_DP_BASIC``
(client_id:client_secret base64) est échangé contre un bearer JWT (~1 h, mis en
cache). Données : GRIB **sous-ensemblé côté serveur** à une petite bbox autour du
point (≈ 200 o par variable × échéance) → ``eccodes`` → valeur au point. MF n'autorise
qu'une tranche 2D par requête → **une requête par (variable, échéance)** ; on
parallélise.

Sortie : DataFrame en **unités socle** (T en K, HR/nébulosité en fraction 0-1, pluie
en mm, vent en m/s, ``rayonnement_global`` en J/m²/h, direction en deg), mêmes
conventions que ``OpenMeteoSingleRuns`` (cf. ``appliquer_conventions_socle``), pour
brancher la section semaine sans changer le pipeline.

Dépendance : ``eccodes`` (binaire C + bindings) — ajouté à ``environment-dev.yml``.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from eccodes import (
    codes_get_array,
    codes_new_from_message,
    codes_release,
)

logger = logging.getLogger(__name__)

TOKEN_URL = "https://portail-api.meteofrance.fr/token"
WCS_BASE = (
    "https://public-api.meteofrance.fr/public/arpege/1.0/wcs/MF-NWP-GLOBAL-ARPEGE-025-GLOBE-WCS"
)
ENV_BASIC = "METEOFRANCE_DP_BASIC"

# Demi-côté de la bbox de sous-ensemblage (deg) : ~0,13° → la maille la plus
# proche du point (1-2 mailles à 0,25°), dont on prend la plus proche.
_BBOX_DEG = 0.13
# Parallélisme des petites requêtes WCS. Modeste : le quota MF est **par minute**
# et ce sont les bursts qui le font sauter (~200 en parallèle KO ; ~70 séquentielles
# OK). Le limiteur ci-dessous est le vrai garde-fou ; les workers ne font qu'amortir
# la latence réseau.
_MAX_WORKERS = 6
# Plafond d'appels par minute, sous la limite réelle observée (~85/min). Monté de
# 50 à 65 (2026-06-14) pour réduire le plancher du fetch matin (~517 req → ~8 min de
# pacing au lieu de ~10). À monter encore prudemment en surveillant le throttle.
_MAX_PAR_MINUTE = 65


class ArpegeIndisponibleError(RuntimeError):
    """Auth ou WCS MF inaccessible (le run ne peut pas être construit)."""


class _LimiteurDebit:
    """Cap thread-safe à N appels par fenêtre glissante de 60 s (quota MF/min)."""

    def __init__(self, max_par_minute: int) -> None:
        self.max = max_par_minute
        self._lock = threading.Lock()
        self._instants: deque[float] = deque()

    def acquerir(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._instants and now - self._instants[0] >= 60.0:
                    self._instants.popleft()
                if len(self._instants) < self.max:
                    self._instants.append(now)
                    return
                attente = 60.0 - (now - self._instants[0]) + 0.05
            time.sleep(attente)


_LIMITEUR = _LimiteurDebit(_MAX_PAR_MINUTE)


# ---------------------------------------------------------------------------
# OAuth : identifiant Basic → bearer (~1 h), mis en cache module.
# ---------------------------------------------------------------------------
_token_cache: dict[str, float | str] = {"valeur": "", "expire": 0.0}


def _bearer(session: requests.Session, basic: str) -> str:
    """Bearer OAuth, mis en cache jusqu'à ~60 s avant expiration."""
    if _token_cache["valeur"] and time.time() < float(_token_cache["expire"]):
        return str(_token_cache["valeur"])
    resp = session.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {basic}"},
        timeout=30,
        verify=False,  # noqa: S501 — chaîne de certif MF capricieuse (cf. -k)
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload["access_token"]
    _token_cache["valeur"] = token
    _token_cache["expire"] = time.time() + float(payload.get("expires_in", 3600)) - 60
    return token


# ---------------------------------------------------------------------------
# Mapping variable socle → coverage MF (+ niveau, accumulation, conversion).
# ---------------------------------------------------------------------------
#: Variables instantanées : (préfixe coverage, hauteur ou None, conversion → socle).
_VARS_INSTANT: dict[str, tuple[str, int | None, str]] = {
    "temperature_2m": ("TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 2, "K"),
    "humidite_relative": ("RELATIVE_HUMIDITY__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 2, "pct_frac"),
    "rafales_vent_10m": ("WIND_SPEED_GUST__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 10, "ms"),
    "cloud_cover": ("TOTAL_CLOUD_COVER__GROUND_OR_WATER_SURFACE", None, "pct_frac"),
    # Type de précip MF (code GRIB 4.201 → phase) pour le picto semaine unifié
    # (ADR-0021) ; absent à l'analyse (+0 h) → 404 toléré (NaN). « code » = identité.
    "type_precip": ("PRECIPITATION_TYPE_60_MIN__GROUND_OR_WATER_SURFACE", None, "code"),
    # U/V à 10 m → vitesse + direction (MF n'expose pas WIND_DIRECTION directement).
    "_u10": ("U_COMPONENT_OF_WIND__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 10, "ms"),
    "_v10": ("V_COMPONENT_OF_WIND__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 10, "ms"),
}
#: Variables accumulées (suffixe _PT{n}H selon le pas) : (préfixe, conversion).
#: Le rayonnement sort en ``rayonnement_global`` (convention socle, J/m²/h).
_VARS_ACCUM: dict[str, tuple[str, str]] = {
    "precipitation": ("TOTAL_PRECIPITATION__GROUND_OR_WATER_SURFACE", "mm"),
    "rayonnement_global": (
        "DOWNWARD_SHORT_WAVE_RADIATION_FLUX__GROUND_OR_WATER_SURFACE",
        "J_par_h",
    ),
}


def vent_vitesse_direction(u, v):
    """(U, V) m/s → (vitesse m/s, direction d'où vient le vent en deg).

    Convention météo : direction = secteur d'origine (N=0, E=90, S=180, O=270).
    Vectorisé (scalaires ou Series). Ex. U=0,V=-1 (souffle vers le sud) → 0° (nord).
    """
    vitesse = np.hypot(u, v)
    direction = (180.0 + np.degrees(np.arctan2(u, v))) % 360.0
    return vitesse, direction


def _convertir(valeur: float, mode: str, fenetre_s: float = 3600.0) -> float:
    """Convertit la valeur GRIB MF vers la convention socle."""
    if mode == "pct_frac":  # % → fraction 0-1 (HR, nébulosité)
        return valeur / 100.0
    if mode == "J_par_h":  # J/m² accumulés sur la fenêtre → J/m²/h (socle)
        return valeur / (fenetre_s / 3600.0)
    return valeur  # K, m/s, mm : déjà en unités socle


# ---------------------------------------------------------------------------
# WCS : échéances disponibles + extraction d'une valeur au point.
# ---------------------------------------------------------------------------
def _coverage_run(run_utc: pd.Timestamp) -> str:
    """Suffixe de run dans les CoverageId : ``2026-06-11T00.00.00Z``."""
    return run_utc.tz_convert("UTC").strftime("%Y-%m-%dT%H.%M.%SZ")


def _echeances(
    session: requests.Session,
    token: str,
    run_utc: pd.Timestamp,
    wcs_base: str = WCS_BASE,
    coverage_prefixe: str = "TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND",
) -> list[pd.Timestamp]:
    """Échéances (valid times) disponibles, lues dans le DescribeCoverage d'un champ.

    ``wcs_base`` permet de réutiliser ce helper pour un autre modèle MF servi par le
    même WCS (AROME, etc.) ; défaut = ARPEGE. ``coverage_prefixe`` cible le champ dont
    on lit l'axe temps (défaut T° 2 m ; ex. ``N_PROBA_PRECI06_1__GROUND_OR_WATER_SURFACE``
    pour PE-AROME, qui n'a pas de T°). Tous deux rétrocompatibles.
    """
    cid = f"{coverage_prefixe}___{_coverage_run(run_utc)}"
    resp = session.get(
        f"{wcs_base}/DescribeCoverage",
        params={"service": "WCS", "version": "2.0.1", "coverageid": cid},
        headers={"Authorization": f"Bearer {token}"},
        timeout=40,
        verify=False,  # noqa: S501
    )
    resp.raise_for_status()
    # Plusieurs axes ont des <coefficients> (hauteur en m, temps en s) : l'axe TEMPS
    # est celui dont les offsets sont des multiples de 3600 (secondes depuis le run).
    offsets: list[int] | None = None
    for bloc in re.findall(r"<gmlrgrid:coefficients>([0-9 ]+)</gmlrgrid:coefficients>", resp.text):
        vals = [int(x) for x in bloc.split()]
        if vals and max(vals) > 3600 and all(v % 3600 == 0 for v in vals):
            offsets = vals
            break
    if offsets is None:
        raise ArpegeIndisponibleError("Axe temps introuvable dans DescribeCoverage.")
    return [run_utc + pd.Timedelta(seconds=o) for o in offsets]


def _valeur_point(
    session: requests.Session,
    token: str,
    coverage_id: str,
    valid: pd.Timestamp,
    lat: float,
    lon: float,
    hauteur: int | None,
    wcs_base: str = WCS_BASE,
) -> float:
    """GetCoverage sous-ensemblé (bbox + hauteur + 1 échéance) → valeur au point.

    ``wcs_base`` : modèle MF cible (défaut ARPEGE) — réutilisable pour AROME, etc.
    """
    subset = [
        f"long({lon - _BBOX_DEG},{lon + _BBOX_DEG})",
        f"lat({lat - _BBOX_DEG},{lat + _BBOX_DEG})",
        f"time({valid.tz_convert('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')})",
    ]
    if hauteur is not None:
        subset.append(f"height({hauteur})")
    params = {
        "service": "WCS",
        "version": "2.0.1",
        "coverageid": coverage_id,
        "subset": subset,
        "format": "application/wmo-grib",
    }
    # Cap par minute + retry si on touche quand même le throttle (fenêtre/min).
    for tentative in range(3):
        _LIMITEUR.acquerir()
        resp = session.get(
            f"{wcs_base}/GetCoverage",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
            verify=False,  # noqa: S501
        )
        if resp.content.startswith(b"GRIB"):
            break
        if b"throttled" in resp.content.lower() and tentative < 2:
            # Quota MF sur fenêtre glissante de 60 s : ~10 s suffisent à libérer des
            # jetons (inutile d'attendre 60 s, qui gonflaient le fetch matin).
            logger.warning("ARPEGE direct : throttle, attente 10 s avant retry.")
            time.sleep(10)
            continue
        raise ArpegeIndisponibleError(
            f"GetCoverage {coverage_id} @ {valid} : {resp.content[:160]!r}"
        )
    gid = codes_new_from_message(resp.content)
    if gid is None:
        raise ArpegeIndisponibleError(f"GRIB illisible : {coverage_id}")
    try:
        lats = codes_get_array(gid, "latitudes")
        lons = [((x + 180.0) % 360.0 - 180.0) for x in codes_get_array(gid, "longitudes")]
        vals = codes_get_array(gid, "values")
    finally:
        codes_release(gid)
    i = min(range(len(vals)), key=lambda j: (lats[j] - lat) ** 2 + (lons[j] - lon) ** 2)
    return float(vals[i])


def _suffixe_accum(fenetre_s: float) -> str:
    """``_PT1H`` / ``_PT3H``… selon la fenêtre d'accumulation (pas entre échéances)."""
    return f"_PT{int(round(fenetre_s / 3600.0))}H"


# Colonnes accumulées (réparties sur leur fenêtre lors du rééchantillonnage).
# ``precipitation_neige`` (AROME/ECMWF, absent d'ARPEGE) répartie comme la pluie.
_COLS_ACCUM_FINALES = ("precipitation", "precipitation_neige", "rayonnement_global")
#: Cumuls répartis « total/n par heure » (vs flux moyen répété, ex. rayonnement).
_COLS_ACCUM_REPARTIES = ("precipitation", "precipitation_neige")


def _reechantillonner_horaire(df: pd.DataFrame, run_utc: pd.Timestamp) -> pd.DataFrame:
    """Ramène un df d'échéances mixtes (horaire ≤ 48 h puis 3-horaire) au pas horaire.

    ``etp_horaire_socle`` suppose des pas **horaires** : au-delà de 48 h (3-horaire),
    l'ETP par ligne serait sous-comptée. On interpole les variables instantanées et
    on répartit les accumulées sur les heures de leur fenêtre : pluie = total/n par
    heure (conserve le cumul), rayonnement = flux moyen (W/m²) répété sur chaque heure.
    No-op si le df est déjà horaire.
    """
    idx_h = pd.date_range(run_utc, df.index.max(), freq="h")
    if len(idx_h) == len(df.index):
        return df
    out = pd.DataFrame(index=pd.DatetimeIndex(idx_h, name="time"))
    for c in [c for c in df.columns if c not in _COLS_ACCUM_FINALES]:
        out[c] = df[c].reindex(out.index).interpolate(method="time")
    for c in _COLS_ACCUM_FINALES:
        if c not in df.columns:  # ARPEGE n'a pas la neige → on saute proprement.
            continue
        serie = pd.Series(0.0, index=out.index)
        prev = run_utc
        for t in df.index[1:]:
            heures = out.index[(out.index > prev) & (out.index <= t)]
            if len(heures):
                val = float(df.at[t, c])  # type: ignore[arg-type]  # colonne float au runtime
                serie.loc[heures] = (val / len(heures)) if c in _COLS_ACCUM_REPARTIES else val
            prev = t
        out[c] = serie
    return out


class MeteoFranceArpege:
    """Source ARPEGE directe MF (WCS Données Publiques), au point, en unités socle."""

    def __init__(self, basic: str | None = None, session: requests.Session | None = None) -> None:
        self.basic = basic or os.environ.get(ENV_BASIC, "")
        self.session = session or requests.Session()

    def obtenir_run(
        self,
        run_utc: pd.Timestamp,
        latitude: float,
        longitude: float,
        horizon_jours: int,
        cache_dir: str | Path | None = None,
    ) -> pd.DataFrame:
        """Série horaire au point pour le run, jusqu'à ``horizon_jours``.

        Renvoie un DataFrame indexé UTC, colonnes socle (cf. module). Les accumulées
        (pluie, rayonnement) sont calées sur la fenêtre entre échéances ; la 1ʳᵉ
        échéance (+0 h) n'en a pas → 0. La direction du vent est dérivée d'U/V 10 m.

        ``cache_dir`` : si fourni, le run (déterministe) est mis en cache parquet par
        run+point → l'envoi de l'après-midi réutilise le fetch du matin (00Z) au lieu
        de refaire ~500 requêtes. En CI, persister ce dossier entre les deux jobs
        (actions/cache) ; en local, il persiste naturellement.
        """
        if not self.basic:
            raise ArpegeIndisponibleError(f"Identifiant {ENV_BASIC} absent.")
        run_utc = run_utc.tz_convert("UTC") if run_utc.tzinfo else run_utc.tz_localize("UTC")
        chemin_cache: Path | None = None
        if cache_dir is not None:
            chemin_cache = Path(cache_dir) / (
                f"arpege_{run_utc:%Y%m%dT%HZ}_{latitude:.3f}_{longitude:.3f}_h{horizon_jours}.parquet"
            )
            if chemin_cache.exists():
                logger.info("ARPEGE direct : run servi depuis le cache (%s).", chemin_cache.name)
                return pd.read_parquet(chemin_cache)
        token = _bearer(self.session, self.basic)
        echeances = [
            t
            for t in _echeances(self.session, token, run_utc)
            if t <= run_utc + pd.Timedelta(days=horizon_jours)
        ]
        run_str = _coverage_run(run_utc)

        # Fenêtre d'accumulation par échéance = écart avec l'échéance précédente.
        fenetres = {echeances[0]: 0.0}
        for prev, cur in zip(echeances, echeances[1:], strict=False):
            fenetres[cur] = (cur - prev).total_seconds()

        taches: list[tuple[str, pd.Timestamp, str, int | None, str, float]] = []
        for col, (prefixe, hauteur, conv) in _VARS_INSTANT.items():
            for t in echeances:
                # Les rafales ne sont pas dans l'analyse (+0 h) → 404 attendu ; on saute
                # (la 1ʳᵉ échéance reste NaN, sans intérêt : la semaine part de +1 h).
                if col == "rafales_vent_10m" and t == echeances[0]:
                    continue
                taches.append((col, t, f"{prefixe}___{run_str}", hauteur, conv, 3600.0))
        for col, (prefixe, conv) in _VARS_ACCUM.items():
            for t in echeances:
                fen = fenetres[t]
                if fen <= 0:  # +0 h : pas d'accumulation
                    continue
                cid = f"{prefixe}___{run_str}{_suffixe_accum(fen)}"
                taches.append((col, t, cid, None, conv, fen))

        def _run(tache):
            col, t, cid, hauteur, conv, fen = tache
            try:
                brut = _valeur_point(self.session, token, cid, t, latitude, longitude, hauteur)
                return col, t, _convertir(brut, conv, fen)
            except ArpegeIndisponibleError as e:
                logger.warning("ARPEGE direct : %s", e)
                return col, t, np.nan

        cols = list(_VARS_INSTANT) + list(_VARS_ACCUM)
        df = pd.DataFrame(index=pd.DatetimeIndex(echeances, name="time"), columns=cols, dtype=float)
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            for col, t, val in pool.map(_run, taches):
                df.at[t, col] = val

        # Accumulées : +0 h = 0 (pas de fenêtre).
        for col in _VARS_ACCUM:
            df.loc[echeances[0], col] = 0.0
        # Pas horaire uniforme (ARPEGE est 3-horaire au-delà de 48 h) → ETP correcte.
        df = _reechantillonner_horaire(df, run_utc)
        # Vent : vitesse + direction depuis U/V, puis on retire les colonnes brutes.
        df["vitesse_vent_10m"], df["direction_vent_deg"] = vent_vitesse_direction(
            df["_u10"], df["_v10"]
        )
        df = df.drop(columns=["_u10", "_v10"])
        if chemin_cache is not None:
            chemin_cache.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(chemin_cache)
            logger.info("ARPEGE direct : run mis en cache (%s).", chemin_cache.name)
        return df
