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

import time
from dataclasses import dataclass, field

import pandas as pd
import requests

from .openmeteo import HOURLY_VARIABLES_DEFAUT, RENAME_VERS_SOCLE

API_URL = "https://archive-api.open-meteo.com/v1/archive"

# Open-Meteo applique des quotas par IP (free tier ≈ 5000 req/h,
# 600/min). En CI on tape la borne plus vite qu'il n'y paraît : un
# build climato = 30 requêtes annuelles et plusieurs builds consécutifs
# (pushs rapides successifs) suffisent à déclencher un 429.
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_TENTATIVES = 4
_BACKOFF_BASE_S = 5.0


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
        response = self._get_avec_retry(params)
        return self._parse(response.json())

    def _get_avec_retry(self, params: dict[str, str]) -> requests.Response:
        """GET avec retry/backoff exponentiel sur 429 et 5xx.

        Respecte ``Retry-After`` si présent (Open-Meteo le renvoie sur
        certains 429). Sinon backoff exponentiel avec base 5 s.
        """
        for tentative in range(1, _MAX_TENTATIVES + 1):
            response = self.session.get(API_URL, params=params, timeout=120)
            if response.status_code not in _RETRY_STATUSES:
                response.raise_for_status()
                return response
            if tentative == _MAX_TENTATIVES:
                response.raise_for_status()
            retry_after = response.headers.get("Retry-After")
            attente = (
                float(retry_after)
                if retry_after and retry_after.isdigit()
                else _BACKOFF_BASE_S * (2 ** (tentative - 1))
            )
            time.sleep(attente)
        # Inatteignable (la boucle raise ou return) — pour mypy.
        raise RuntimeError("retry loop exhausted")

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
