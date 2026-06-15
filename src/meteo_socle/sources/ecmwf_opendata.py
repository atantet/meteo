"""ECMWF IFS HRES déterministe **direct** depuis ECMWF Open Data, au point.

Alternative à Open-Meteo pour la **ligne ECMWF** de la tendance semaine :
Open-Meteo a des trous d'ingestion (constaté mi-juin sur les **rafales** ECMWF,
servies en pointillé). ECMWF Open Data (``data.ecmwf.int``, **libre, sans clé**)
sert le run complet. On télécharge les champs **globaux** (GRIB) puis on extrait
le point le plus proche — bien plus simple que le WCS MF : **un seul téléchargement
multi-échéances** par appel, pas d'OAuth ni de quota.

Sortie : DataFrame en **unités socle** (T en K, HR/nébulosité en fraction 0-1,
pluie en mm, vent en m/s, ``rayonnement_global`` en J/m²/h, direction en deg),
mêmes conventions que ``MeteoFranceArpege`` / ``OpenMeteoSingleRuns`` → branchable
sans changer le pipeline (cf. ADR-0018, miroir d'ADR-0016 pour ARPEGE).

Particularités ECMWF Open Data :
- HRES sert **3-horaire** jusqu'à 144 h puis **6-horaire** jusqu'à 240 h → on
  rééchantillonne à l'horaire (l'ETP socle suppose l'horaire).
- ``tp`` (pluie) et ``ssrd`` (rayonnement) sont **cumulés depuis le run** → on
  dé-accumule (différence d'échéances consécutives).
- Pas de HR ni de direction directes : HR dérivée du point de rosée ``2d`` +
  ``2t`` (Magnus), direction d'``10u``/``10v``.

Dépendances : ``ecmwf-opendata`` (client), ``cfgrib`` + ``eccodes`` (lecture GRIB)
— ajoutées à ``environment-dev.yml``.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from meteo_socle.sources.meteofrance_arpege import (
    _reechantillonner_horaire,  # helper NWP→socle partagé (rééchantillonnage horaire)
    vent_vitesse_direction,
)

logger = logging.getLogger(__name__)


class EcmwfIndisponibleError(RuntimeError):
    """Run ECMWF Open Data non récupérable (réseau, run absent, GRIB illisible)."""


# Paramètres Open Data (oper/fc) → nom court cfgrib en sortie. ``ptype``/``sf``
# ajoutés pour le picto (phase pluie/neige/verglas cohérente 0-10 j, cf. ADR-0021) —
# disponibles en open data (vérifié 2026-06-15).
_PARAMS_OPENDATA = ["2t", "2d", "10u", "10v", "10fg", "tcc", "ssrd", "tp", "ptype", "sf"]
# Nom court cfgrib → colonne socle (variables **instantanées**).
_INSTANT = {
    "t2m": "temperature_2m",  # K
    "fg10": "rafales_vent_10m",  # m/s
    "tcc": "cloud_cover",  # fraction 0-1
    "u10": "_u10",  # m/s → vitesse + direction
    "v10": "_v10",
}
# Variables **cumulées depuis le run** (à dé-accumuler).
_CUMUL = {
    "tp": "precipitation",  # m cumulés → mm sur la fenêtre
    "ssrd": "rayonnement_global",  # J/m² cumulés → J/m²/h sur la fenêtre
}
# Champs picto **optionnels** (NaN si absents du run, sans faire échouer la cascade).
# ``ptype`` = code GRIB de type de précip (phase) ; ``sf`` = neige cumulée (m → mm).
_INSTANT_OPT = {"ptype": "type_precip"}
_CUMUL_OPT = {"sf": "precipitation_neige"}


def _humidite_relative(t2m_k: pd.Series, d2m_k: pd.Series) -> pd.Series:
    """HR (fraction 0-1) depuis T° et point de rosée (K), formule de Magnus (WMO).

    RH = e_s(Td) / e_s(T) avec e_s(x) ∝ exp(a·x / (b + x)), x en °C
    (a = 17.62, b = 243.12 °C, au-dessus de l'eau). Bornée à [0, 1].
    """
    t_c = t2m_k - 273.15
    td_c = d2m_k - 273.15
    a, b = 17.62, 243.12
    rh = np.exp(a * td_c / (b + td_c) - a * t_c / (b + t_c))
    return rh.clip(lower=0.0, upper=1.0)


def _steps_horizon(horizon_jours: int) -> list[int]:
    """Échéances (h) d'un run HRES 00/12Z : 3-horaire ≤ 144 h puis 6-horaire ≤ 240 h."""
    hmax = min(horizon_jours * 24, 240)
    steps = list(range(0, min(hmax, 144) + 1, 3))
    if hmax > 144:
        steps += list(range(150, hmax + 1, 6))
    return steps


def _serie_point(datasets: list, shortname: str, latitude: float, longitude: float) -> pd.Series:
    """Série temporelle (indexée valid_time UTC) du point le plus proche pour ``shortname``.

    Cherche la variable dans la liste de datasets cfgrib (split par type de niveau /
    d'accumulation). Lève ``EcmwfIndisponibleError`` si absente.
    """
    for ds in datasets:
        if shortname not in ds.data_vars:
            continue
        # Grille ECMWF Open Data en longitude **-180..180** (vérifié) : on passe la
        # longitude telle quelle (un % 360 tomberait dans le Pacifique → faux point).
        pt = ds[shortname].sel(latitude=latitude, longitude=longitude, method="nearest")
        valeurs = np.atleast_1d(np.asarray(pt.values, dtype=float))
        vt = pd.DatetimeIndex(pd.to_datetime(np.atleast_1d(pt["valid_time"].values), utc=True))
        return pd.Series(valeurs, index=vt, name=shortname).sort_index()
    raise EcmwfIndisponibleError(f"Variable {shortname} absente du GRIB ECMWF Open Data.")


def _deaccumuler(cumul: pd.Series, mode: str) -> pd.Series:
    """Cumul-depuis-le-run → valeur **par fenêtre** (différence d'échéances).

    ``mode`` = ``"mm"`` (pluie : incrément en m → mm) ou ``"J_par_h"`` (rayonnement :
    incrément J/m² sur la fenêtre → J/m²/h). 1ʳᵉ échéance (+0 h) → 0.
    """
    s = cumul.sort_index()
    increments = s.diff()
    increments.iloc[0] = 0.0
    # Incréments négatifs (réinitialisation / bruit) → 0.
    increments = increments.clip(lower=0.0)
    if mode == "mm":
        return increments * 1000.0  # m → mm
    # J/m² sur la fenêtre → J/m²/h : diviser par la durée de la fenêtre (h).
    heures = s.index.to_series().diff().dt.total_seconds() / 3600.0
    heures.iloc[0] = 1.0
    return increments / heures


def _assembler(
    datasets: list,
    run_utc: pd.Timestamp,
    horizon_jours: int,
    latitude: float,
    longitude: float,
) -> pd.DataFrame:
    """Datasets cfgrib → DataFrame horaire en unités socle (testable hors réseau)."""
    series: dict[str, pd.Series] = {}
    for shortname, col in _INSTANT.items():
        series[col] = _serie_point(datasets, shortname, latitude, longitude)
    t2m = series["temperature_2m"]
    d2m = _serie_point(datasets, "d2m", latitude, longitude)
    series["humidite_relative"] = _humidite_relative(t2m, d2m.reindex(t2m.index))
    for shortname, col in _CUMUL.items():
        brut = _serie_point(datasets, shortname, latitude, longitude)
        series[col] = _deaccumuler(brut, "mm" if col == "precipitation" else "J_par_h")
    # Champs picto optionnels : NaN (sur l'index t2m) s'ils manquent du run.
    for shortname, col in _INSTANT_OPT.items():
        try:
            series[col] = _serie_point(datasets, shortname, latitude, longitude)
        except EcmwfIndisponibleError:
            series[col] = pd.Series(np.nan, index=t2m.index, name=col)
    for shortname, col in _CUMUL_OPT.items():
        try:
            brut = _serie_point(datasets, shortname, latitude, longitude)
            series[col] = _deaccumuler(brut, "mm")  # neige : m → mm comme la pluie
        except EcmwfIndisponibleError:
            series[col] = pd.Series(np.nan, index=t2m.index, name=col)

    df = pd.DataFrame(series)
    df.index.name = "time"
    df = df.sort_index()
    df = df[df.index <= run_utc + pd.Timedelta(days=horizon_jours)]

    # Pas horaire uniforme (3 h/6 h natif) → ETP socle correcte.
    df = _reechantillonner_horaire(df, run_utc)
    # Vent : vitesse + direction depuis U/V, puis on retire les colonnes brutes.
    df["vitesse_vent_10m"], df["direction_vent_deg"] = vent_vitesse_direction(
        df["_u10"], df["_v10"]
    )
    return df.drop(columns=["_u10", "_v10"])


class EcmwfOpendata:
    """Source ECMWF IFS HRES directe (Open Data), au point, en unités socle."""

    def __init__(self, client=None) -> None:
        # Client injectable pour les tests ; sinon créé à la volée (import paresseux
        # pour ne pas exiger ecmwf-opendata quand le flag est OFF).
        self._client = client

    def _telecharger(self, run_utc: pd.Timestamp, steps: list[int], cible: Path) -> None:
        """Télécharge le GRIB multi-échéances du run dans ``cible``."""
        client = self._client
        if client is None:
            from ecmwf.opendata import Client

            client = Client(source="ecmwf")
        try:
            client.retrieve(
                type="fc",
                stream="oper",
                param=_PARAMS_OPENDATA,
                step=steps,
                date=run_utc.strftime("%Y%m%d"),
                time=int(run_utc.hour),
                target=str(cible),
            )
        except Exception as e:  # noqa: BLE001 — toute erreur client → indisponible (cascade)
            raise EcmwfIndisponibleError(f"Open Data ECMWF injoignable : {e}") from e

    def obtenir_run(
        self,
        run_utc: pd.Timestamp,
        latitude: float,
        longitude: float,
        horizon_jours: int,
        cache_dir: str | Path | None = None,
    ) -> pd.DataFrame:
        """Série horaire au point pour le run HRES, jusqu'à ``horizon_jours``.

        DataFrame indexé UTC, colonnes socle. ``cache_dir`` : run mis en cache
        parquet par run+point (l'après-midi réutilise le fetch du matin), comme
        ``MeteoFranceArpege`` (cf. ADR-0016/0018).
        """
        run_utc = run_utc.tz_convert("UTC") if run_utc.tzinfo else run_utc.tz_localize("UTC")
        chemin_cache: Path | None = None
        if cache_dir is not None:
            chemin_cache = Path(cache_dir) / (
                f"ecmwf_{run_utc:%Y%m%dT%HZ}_{latitude:.3f}_{longitude:.3f}_h{horizon_jours}.parquet"
            )
            if chemin_cache.exists():
                logger.info("ECMWF Open Data : run servi depuis le cache (%s).", chemin_cache.name)
                return pd.read_parquet(chemin_cache)

        import cfgrib

        steps = _steps_horizon(horizon_jours)
        with tempfile.TemporaryDirectory() as tmp:
            grib = Path(tmp) / "ecmwf_hres.grib2"
            self._telecharger(run_utc, steps, grib)
            try:
                datasets = cfgrib.open_datasets(str(grib))
            except Exception as e:  # noqa: BLE001 — GRIB illisible → indisponible
                raise EcmwfIndisponibleError(f"GRIB ECMWF illisible : {e}") from e
            df = _assembler(datasets, run_utc, horizon_jours, latitude, longitude)

        if chemin_cache is not None:
            chemin_cache.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(chemin_cache)
            logger.info("ECMWF Open Data : run mis en cache (%s).", chemin_cache.name)
        return df
