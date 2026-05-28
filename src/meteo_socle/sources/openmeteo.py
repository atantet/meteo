"""Source météo Open-Meteo pour les prévisions 0-7 jours.

Wrapper REST autour de l'API publique Open-Meteo (https://open-meteo.com).
Agit comme passerelle multi-modèles vers AROME France HD (1.3 km,
J0-J3), ARPEGE-EU (10 km), ECMWF IFS (9 km, J0-J10), ICON-D2, GFS,
sans nécessiter de jeton d'authentification.

Convention d'unités en sortie : aligné sur le socle (cf.
`meteo_socle.sources.meteofrance` et le calcul ETP FAO).

- ``temperature_2m`` : K
- ``humidite_relative`` : fraction 0-1
- ``vitesse_vent_10m`` : m s⁻¹
- ``rafales_vent_10m`` : m s⁻¹
- ``precipitation`` : mm
- ``rayonnement_global`` : J m⁻² h⁻¹
- ``etp_open_meteo`` : mm h⁻¹ (ET₀ FAO calculée par Open-Meteo —
  utile pour validation croisée vs notre calcul socle ETP FAO)
- ``cloud_cover`` : fraction 0-1 (utile pour fallback R_s, cf. ADR-0006)

Limites
-------

- **Service tiers privé** (basé en Allemagne). Durabilité non garantie
  sur 5+ ans — cf. principe n°2 et ADR-0002. L'abstraction
  ``SourceMeteo`` au-dessus permet de substituer un autre fournisseur
  si Open-Meteo ferme.
- **Quota gratuit** : 10 000 requêtes/jour pour usage non commercial.
  Pour App 1 Veille (~30 req/mois) très en-dessous.
- **Pas d'authentification** : aucun secret à gérer.

Référence API : https://open-meteo.com/en/docs
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import requests

API_URL = "https://api.open-meteo.com/v1/forecast"

# Variables horaires demandées par défaut. Open-Meteo accepte ces noms
# en snake_case dans le paramètre `hourly`. Les unités natives sont
# converties au moment du parsing pour respecter les conventions socle.
HOURLY_VARIABLES_DEFAUT: list[str] = [
    "temperature_2m",  # °C → K
    "relative_humidity_2m",  # % → fraction
    "precipitation",  # mm
    "precipitation_probability",  # % (0-100, gardé tel quel)
    "wind_speed_10m",  # m/s (via wind_speed_unit=ms)
    "wind_gusts_10m",  # m/s
    "wind_direction_10m",  # degrés (0=N, 90=E, 180=S, 270=W)
    "shortwave_radiation",  # W/m² → J/m²/h
    "et0_fao_evapotranspiration",  # mm/h
    "cloud_cover",  # % → fraction
]

# Mapping noms Open-Meteo → noms socle (équivalent à
# `meteofrance.renommer_variables`).
RENAME_VERS_SOCLE: dict[str, str] = {
    "temperature_2m": "temperature_2m",
    "relative_humidity_2m": "humidite_relative",
    "precipitation": "precipitation",
    "precipitation_probability": "probabilite_pluie_pct",
    "wind_speed_10m": "vitesse_vent_10m",
    "wind_gusts_10m": "rafales_vent_10m",
    "wind_direction_10m": "direction_vent_deg",
    "shortwave_radiation": "rayonnement_global",
    "et0_fao_evapotranspiration": "etp_open_meteo",
    "cloud_cover": "cloud_cover",
}


@dataclass
class OpenMeteoForecast:
    """Client Open-Meteo pour les prévisions horaires multi-modèles.

    Parameters
    ----------
    modele :
        Identifiant du modèle Open-Meteo. ``"best_match"`` (défaut)
        compose automatiquement plusieurs modèles selon l'horizon ;
        des modèles spécifiques sont disponibles (par exemple
        ``"meteofrance_arome_france_hd"``, ``"ecmwf_ifs025"``).
    session :
        Session HTTP réutilisable. Auto-créée si non fournie ; injecter
        une session mock dans les tests.
    """

    modele: str = "best_match"
    session: requests.Session = field(default_factory=requests.Session)

    def obtenir_prevision(
        self,
        latitude: float,
        longitude: float,
        horizon_jours: int,
        variables: list[str] | None = None,
    ) -> pd.DataFrame:
        """Récupère la prévision horaire pour un point sur N jours.

        Effectue un appel HTTP GET à Open-Meteo, parse le JSON,
        applique les conversions d'unités vers les conventions socle.

        Parameters
        ----------
        latitude, longitude :
            Coordonnées du site en degrés décimaux WGS84.
        horizon_jours :
            Nombre de jours de prévision (1-16, Open-Meteo plafond).
        variables :
            Liste de noms Open-Meteo. Défaut :
            ``HOURLY_VARIABLES_DEFAUT``.

        Returns
        -------
        pd.DataFrame
            DataFrame indexé par DatetimeIndex tz-aware UTC, avec
            colonnes renommées et unités converties.

        Raises
        ------
        requests.HTTPError
            En cas de réponse non-200.
        """
        params = self._build_params(latitude, longitude, horizon_jours, variables)
        response = self.session.get(API_URL, params=params, timeout=30)
        response.raise_for_status()
        return self._parse(response.json())

    def _build_params(
        self,
        latitude: float,
        longitude: float,
        horizon_jours: int,
        variables: list[str] | None,
    ) -> dict[str, str]:
        """Construit les query parameters de la requête Open-Meteo."""
        vars_list = variables if variables is not None else HOURLY_VARIABLES_DEFAUT
        return {
            "latitude": f"{latitude}",
            "longitude": f"{longitude}",
            "hourly": ",".join(vars_list),
            "models": self.modele,
            "forecast_days": str(horizon_jours),
            "timezone": "UTC",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
        }

    @staticmethod
    def _parse(payload: dict) -> pd.DataFrame:
        """Convertit la réponse JSON Open-Meteo en DataFrame socle.

        Applique les conversions d'unités :
        - T : °C → K (+ 273.15)
        - HR : % → fraction (/ 100)
        - cloud_cover : % → fraction (/ 100)
        - rayonnement : W/m² → J/m²/h (× 3600)
        - autres : identité (vent en m/s, pluie en mm, ETP en mm/h)

        Renomme les colonnes selon ``RENAME_VERS_SOCLE``.
        """
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
