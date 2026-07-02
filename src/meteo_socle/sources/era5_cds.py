"""Client ERA5 ECMWF via API CDS — précipitations quotidiennes.

Remplace OpenMeteoArchive (Open-Meteo abandonné 2026-07-01) pour le pilier
pluie du bulletin eau mensuel. Source : réanalyse ERA5/ERA5T (Copernicus
Climate Data Store), 0.25°, 1940 → présent (~5 j de latence).

Authentification : ~/.cdsapirc ou variables d'environnement CDSAPI_URL /
CDSAPI_KEY (identiques pour GH Actions secrets). Compte gratuit :
https://cds.climate.copernicus.eu.

Cache par année : {cache_dir}/era5_precip_{lat:.4f}_{lon:.4f}_{YYYY}.parquet.
Les années terminées (avant l'année courante) sont mises en cache
indéfiniment. L'année en cours est toujours rechargée (ERA5T incomplet).

Première exécution avec cache froid : chaque année = 1 requête CDS
(~1-5 min/an). Pour GH Actions, activer le cache
~/.cache/meteo_socle/era5/ via l'action actions/cache.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_DIR_DEFAUT = Path.home() / ".cache" / "meteo_socle" / "era5"


class Era5CdsIndisponibleError(RuntimeError):
    """Données ERA5 CDS non récupérables (réseau, auth, quota, GRIB illisible)."""


class Era5Cds:
    """Précipitations quotidiennes ERA5/ERA5T via CDS (cdsapi), avec cache par année.

    Parameters
    ----------
    client :
        Instance ``cdsapi.Client`` injectable (tests offline). ``None`` → créé
        à la volée depuis ~/.cdsapirc ou CDSAPI_URL/CDSAPI_KEY.
    cache_dir :
        Répertoire de cache. Défaut : ``~/.cache/meteo_socle/era5/``.
    """

    def __init__(self, client=None, cache_dir: Path | str | None = None) -> None:
        self._client = client
        self._cache_dir = Path(cache_dir) if cache_dir else _CACHE_DIR_DEFAUT

    # ------------------------------------------------------------------
    # Interne
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import cdsapi
        except ImportError as e:
            raise Era5CdsIndisponibleError("cdsapi non installé") from e
        url = os.environ.get("CDSAPI_URL")
        key = os.environ.get("CDSAPI_KEY")
        kwargs = {"quiet": True}
        if url:
            kwargs["url"] = url
        if key:
            kwargs["key"] = key
        return cdsapi.Client(**kwargs)

    def _cache_path(self, lat: float, lon: float, year: int) -> Path:
        return self._cache_dir / f"era5_precip_{lat:.4f}_{lon:.4f}_{year}.parquet"

    def _fetch_year(self, lat: float, lon: float, year: int) -> pd.Series:
        """Télécharge une année ERA5 via CDS → série quotidienne en mm."""
        client = self._get_client()
        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as f:
            tmp_path = f.name
        try:
            client.retrieve(
                "reanalysis-era5-single-levels",
                {
                    "product_type": "reanalysis",
                    "variable": "total_precipitation",
                    "year": str(year),
                    "month": [f"{m:02d}" for m in range(1, 13)],
                    "day": [f"{d:02d}" for d in range(1, 32)],
                    "time": [f"{h:02d}:00" for h in range(24)],
                    # Boîte minimale centrée sur le point (un seul pixel 0.25°).
                    "area": [lat + 0.125, lon - 0.125, lat - 0.125, lon + 0.125],
                    "data_format": "netcdf",
                    "download_format": "unarchived",
                },
                tmp_path,
            )
        except Exception as e:  # noqa: BLE001 — toute erreur client → indisponible
            raise Era5CdsIndisponibleError(f"CDS indisponible pour {year} : {e}") from e
        try:
            return self._parse_nc(tmp_path, lat, lon)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _parse_nc(self, path: str, lat: float, lon: float) -> pd.Series:
        """netCDF ERA5 → série quotidienne en mm (testable sans réseau)."""
        try:
            import xarray as xr
        except ImportError as e:
            raise Era5CdsIndisponibleError("xarray non installé") from e

        ds = xr.open_dataset(path)
        # CDS netCDF peut nommer la dim 'time' ou 'valid_time' selon la version de l'API.
        time_dim = "valid_time" if "valid_time" in ds.dims else "time"
        tp = ds["tp"]
        # Sélection du point le plus proche.
        pt = tp.sel(latitude=lat, longitude=lon, method="nearest")
        # tp ERA5 = précipitation tombée pendant l'heure précédente (m).
        # Somme calendaire → total journalier en mm.
        daily = pt.resample({time_dim: "1D"}).sum() * 1000.0
        s = daily.to_series()
        s.index = pd.DatetimeIndex(s.index).normalize().tz_localize(None)
        s.index.name = "date"
        return s.dropna()

    # ------------------------------------------------------------------
    # Interface publique (miroir d'OpenMeteoArchive)
    # ------------------------------------------------------------------

    def obtenir_precip_quotidien(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
    ) -> pd.Series:
        """Cumul de précipitation quotidien (mm) entre deux dates (incluses).

        Interface identique à ``OpenMeteoArchive.obtenir_precip_quotidien``.
        Cache par année dans ``cache_dir`` ; années terminées lues depuis
        le cache, année courante toujours rechargée.
        """
        debut = pd.Timestamp(start_date).normalize()
        fin = pd.Timestamp(end_date).normalize()
        annee_courante = pd.Timestamp.now().year
        annees = list(range(debut.year, fin.year + 1))

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        series: list[pd.Series] = []
        for annee in annees:
            chemin = self._cache_path(latitude, longitude, annee)
            if chemin.exists() and annee < annee_courante:
                logger.debug("ERA5 CDS : cache lu (%s).", chemin.name)
                s = pd.read_parquet(chemin)["precip_mm"]
            else:
                logger.info(
                    "ERA5 CDS : fetch année %d (lat=%.4f, lon=%.4f)…", annee, latitude, longitude
                )
                s = self._fetch_year(latitude, longitude, annee)
                if annee < annee_courante and not s.empty:
                    s.to_frame("precip_mm").to_parquet(chemin)
                    logger.info("ERA5 CDS : année %d mise en cache (%s).", annee, chemin.name)
            series.append(s)

        if not series:
            return pd.Series(dtype=float, name="precip_mm")

        combined = pd.concat(series).sort_index()
        mask = (combined.index >= debut) & (combined.index <= fin)
        return combined[mask]
