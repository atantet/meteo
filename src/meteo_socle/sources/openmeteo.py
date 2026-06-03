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

from ._http_retry import get_avec_retry

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
    "weather_code",  # int WMO 4677 (0-99) — pour pictos météo
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
    "weather_code": "weather_code",
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

        **Multi-modèles explicites** : une chaîne séparée par des
        virgules (ex. ``"meteofrance_arome_france_hd,meteofrance_arpege_europe"``)
        demande plusieurs modèles et les **fusionne par priorité** —
        pour chaque variable et chaque heure, la valeur du 1er modèle
        (ordre de la liste) disponible est retenue, les suivants ne
        comblant que les trous (NaN). Cas d'usage : AROME France HD ne
        fournit pas le rayonnement (``shortwave_radiation`` NaN), comblé
        par ARPEGE. Permet une attribution déterministe (pas de boîte
        noire ``best_match``).
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
        past_days: int = 0,
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
        past_days :
            Nombre de jours passés à inclure dans la réponse (0-92).
            0 par défaut = forecast pur. Utile pour les apps qui veulent
            recouvrir la portion 00 h 00 → T+0 du jour courant (App 1
            Veille).

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
        params = self._build_params(latitude, longitude, horizon_jours, variables, past_days)
        response = get_avec_retry(self.session, API_URL, params=params, timeout=30)
        return self._parse(response.json())

    def _build_params(
        self,
        latitude: float,
        longitude: float,
        horizon_jours: int,
        variables: list[str] | None,
        past_days: int = 0,
    ) -> dict[str, str]:
        """Construit les query parameters de la requête Open-Meteo."""
        vars_list = variables if variables is not None else HOURLY_VARIABLES_DEFAUT
        params = {
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
        if past_days > 0:
            params["past_days"] = str(past_days)
        return params

    @staticmethod
    def _fusionner_modeles(df: pd.DataFrame, modeles: list[str]) -> pd.DataFrame:
        """Fusionne les colonnes suffixées ``<var>_<modele>`` par priorité.

        En multi-modèles, Open-Meteo renvoie une colonne par couple
        (variable, modèle), suffixée du nom de modèle. On reconstruit les
        colonnes de base en prenant, cellule par cellule, la valeur du
        **1er modèle de ``modeles``** qui en a une (``combine_first`` en
        cascade) ; les modèles suivants ne comblent que les NaN. Ainsi
        AROME (prioritaire) fournit tout sauf le rayonnement, comblé par
        ARPEGE.
        """
        bases: list[str] = []
        for col in df.columns:
            for m in modeles:
                suffixe = f"_{m}"
                if col.endswith(suffixe):
                    base = col[: -len(suffixe)]
                    if base not in bases:
                        bases.append(base)
                    break
        fusion: dict[str, pd.Series] = {}
        for base in bases:
            serie: pd.Series | None = None
            for m in modeles:  # ordre = priorité décroissante
                col = f"{base}_{m}"
                if col in df.columns:
                    serie = df[col] if serie is None else serie.combine_first(df[col])
            if serie is not None:
                # Force float : une colonne tout-None (ex. rayonnement AROME)
                # arrive en dtype object ; après combine_first le résultat
                # peut rester object, ce qui fait tomber les ufuncs numpy
                # aval sur une division Python (0.0/0.0 → ZeroDivisionError
                # au lieu de NaN). Coercition = sécurité.
                fusion[base] = pd.to_numeric(serie, errors="coerce")
        return pd.DataFrame(fusion, index=df.index)

    def _parse(self, payload: dict) -> pd.DataFrame:
        """Convertit la réponse JSON Open-Meteo en DataFrame socle.

        Applique les conversions d'unités :
        - T : °C → K (+ 273.15)
        - HR : % → fraction (/ 100)
        - cloud_cover : % → fraction (/ 100)
        - rayonnement : W/m² → J/m²/h (× 3600)
        - autres : identité (vent en m/s, pluie en mm, ETP en mm/h)

        En multi-modèles (``modele`` contient des virgules), fusionne
        d'abord les colonnes suffixées par priorité (cf.
        ``_fusionner_modeles``). Renomme les colonnes selon
        ``RENAME_VERS_SOCLE``.
        """
        hourly = payload["hourly"]
        df = pd.DataFrame(hourly)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")

        modeles = [m.strip() for m in self.modele.split(",") if m.strip()]
        if len(modeles) > 1:
            df = self._fusionner_modeles(df, modeles)

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
