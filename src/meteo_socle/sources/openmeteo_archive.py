"""Source historique Open-Meteo archive (ERA5 / ERA5-Land).

Wrapper REST autour de l'API ``archive-api.open-meteo.com`` qui sert
ERA5 et ERA5-Land (ré-analyses ECMWF) sur 1940 → présent.

**Placeholder v0 pour App 3 Climato** : l'ADR-0002 prévoit SAFRAN
(8 km Météo-France) comme source historique de référence pour la
climato locale. ERA5-Land (~10 km) est utilisé temporairement en v0
pour la simplicité d'accès (REST, pas d'auth), avec migration vers
SAFRAN planifiée en v1. Le rapport doit signaler cette substitution.

Convention d'unités en sortie : alignée socle (cf.
``meteo_socle.sources.openmeteo`` pour les détails).

Référence API : https://open-meteo.com/en/docs/historical-weather-api
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import requests

from ._http_retry import get_avec_retry
from .openmeteo import HOURLY_VARIABLES_DEFAUT, RENAME_VERS_SOCLE

API_URL = "https://archive-api.open-meteo.com/v1/archive"


@dataclass
class OpenMeteoArchive:
    """Client Open-Meteo archive pour les données historiques horaires.

    Parameters
    ----------
    modele :
        Identifiant Open-Meteo. ``"era5_land"`` (défaut, ~9 km) pour la
        meilleure résolution disponible sur l'Europe, alternative
        ``"era5"`` (~25 km).
    session :
        Session HTTP réutilisable. Auto-créée si non fournie.
    """

    modele: str = "era5_land"
    session: requests.Session = field(default_factory=requests.Session)

    def obtenir_historique(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
        variables: list[str] | None = None,
    ) -> pd.DataFrame:
        """Récupère l'historique horaire entre deux dates (incluses).

        Parameters
        ----------
        latitude, longitude :
            Coordonnées du site (degrés décimaux).
        start_date, end_date :
            Dates au format ``"YYYY-MM-DD"``.
        variables :
            Liste de noms Open-Meteo. Défaut : variables socle standard.

        Returns
        -------
        pd.DataFrame
            DataFrame indexé par DatetimeIndex tz-aware UTC, colonnes
            renommées vers les conventions socle.

        Raises
        ------
        requests.HTTPError
            En cas de réponse non-200.
        """
        vars_list = variables if variables is not None else HOURLY_VARIABLES_DEFAUT
        params: dict[str, str] = {
            "latitude": f"{latitude}",
            "longitude": f"{longitude}",
            "start_date": start_date,
            "end_date": end_date,
            "hourly": ",".join(vars_list),
            "models": self.modele,
            "timezone": "UTC",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
        }
        response = get_avec_retry(self.session, API_URL, params=params, timeout=120)
        return self._parse(response.json())

    def obtenir_precip_quotidien(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
    ) -> pd.Series:
        """Cumul de précipitation **quotidien** (mm) entre deux dates (incluses).

        Utilise le endpoint ``daily=precipitation_sum`` (bien plus léger que
        l'horaire pour de longues périodes, ex. une normale 1991-2020).

        Returns
        -------
        pd.Series
            Indexée par date (``DatetimeIndex`` naïf, jour), valeurs en mm
            (les jours sans donnée sont écartés).
        """
        params: dict[str, str] = {
            "latitude": f"{latitude}",
            "longitude": f"{longitude}",
            "start_date": start_date,
            "end_date": end_date,
            "daily": "precipitation_sum",
            "models": self.modele,
            "timezone": "UTC",
            "precipitation_unit": "mm",
        }
        response = get_avec_retry(self.session, API_URL, params=params, timeout=120)
        daily = response.json()["daily"]
        s = pd.Series(
            data=pd.to_numeric(daily["precipitation_sum"], errors="coerce"),
            index=pd.to_datetime(daily["time"]),
        )
        s.index.name = "date"
        return s.dropna()

    @staticmethod
    def _parse(payload: dict) -> pd.DataFrame:
        """Réutilise les mêmes conversions que `OpenMeteoForecast._parse`."""
        hourly = payload["hourly"]
        df = pd.DataFrame(hourly)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")

        if "temperature_2m" in df.columns:
            df["temperature_2m"] = df["temperature_2m"] + 273.15
        if "relative_humidity_2m" in df.columns:
            df["relative_humidity_2m"] = df["relative_humidity_2m"] / 100.0
        if "cloud_cover" in df.columns:
            df["cloud_cover"] = df["cloud_cover"] / 100.0
        if "shortwave_radiation" in df.columns:
            df["shortwave_radiation"] = df["shortwave_radiation"] * 3600.0

        df = df.rename(columns=RENAME_VERS_SOCLE)
        return df[[c for c in RENAME_VERS_SOCLE.values() if c in df.columns]]
