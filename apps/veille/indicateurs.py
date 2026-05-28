"""Calcul des indicateurs météorologiques pour l'App 1 Veille.

À partir d'une prévision horaire (DataFrame indexé tz-aware UTC sortie
de ``meteo_socle.sources.openmeteo.OpenMeteoForecast``), calcule les
indicateurs envoyés dans l'email matinal :

- Température min / max sur les prochaines 24 h (proxy nuit / jour)
- Cumuls de pluie 24 / 48 / 72 h
- Vent moyen et rafales maximaux 24 h (km/h)
- ETP cumulée 24 h (caractère séchant du jour)
- Bilan eau (P − ETP) cumulé 7 jours
- Flag "tension irrigation" si l'heuristique config est déclenchée

Les seuils de la tension irrigation viennent de
``config["indicateurs"]["bilan_eau"]["tension_irrigation"]``.

Note v0 : la "nuit" et le "jour" sont approximés par "les prochaines
24 h" (le minimum atterrit naturellement en nuit, le maximum en
journée). Une discrimination plus fine (fenêtres horaires explicites)
peut être ajoutée en v1 si nécessaire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

# Conversions vers unités de présentation utilisateur.
KELVIN_OFFSET: float = 273.15
MS_TO_KMH: float = 3.6


@dataclass
class IndicateursVeille:
    """Bundle des indicateurs calculés pour un envoi matinal."""

    temperature_min_24h_celsius: float
    temperature_max_24h_celsius: float

    cumul_pluie_24h_mm: float
    cumul_pluie_48h_mm: float
    cumul_pluie_72h_mm: float

    vent_max_24h_kmh: float
    rafales_max_24h_kmh: float

    etp_jour_mm: float
    bilan_eau_7j_mm: float

    tension_irrigation: bool


def calculer_indicateurs(
    prevision: pd.DataFrame,
    now_utc: pd.Timestamp,
    config: dict[str, Any],
) -> IndicateursVeille:
    """Calcule les indicateurs Veille depuis une prévision horaire.

    Parameters
    ----------
    prevision :
        DataFrame indexé tz-aware UTC, colonnes selon les conventions
        socle (``temperature_2m`` K, ``precipitation`` mm,
        ``vitesse_vent_10m`` et ``rafales_vent_10m`` m/s,
        ``etp_open_meteo`` mm/h).
    now_utc :
        Référence temporelle. Les lignes du DataFrame antérieures sont
        ignorées.
    config :
        Configuration Veille (cf. ``apps.veille.config.load_config``).
        Seul ``indicateurs.bilan_eau.tension_irrigation`` est lu ici.

    Returns
    -------
    IndicateursVeille
        Dataclass groupant les valeurs synthétiques.

    Raises
    ------
    ValueError
        Si la prévision ne contient aucune heure ≥ ``now_utc``.
    """
    df = prevision.loc[prevision.index >= now_utc].copy()
    if df.empty:
        raise ValueError(
            "La prévision ne contient aucune heure ≥ now_utc — "
            "vérifier la fraîcheur du fetch Open-Meteo."
        )
    df = df.sort_index()

    h24 = df.head(24)
    h48 = df.head(48)
    h72 = df.head(72)
    h168 = df.head(24 * 7)

    temperature_celsius_24h = h24["temperature_2m"] - KELVIN_OFFSET

    etp_24h = float(h24["etp_open_meteo"].sum())
    pluie_24h = float(h24["precipitation"].sum())
    etp_7j = float(h168["etp_open_meteo"].sum())
    pluie_7j = float(h168["precipitation"].sum())
    bilan_7j = pluie_7j - etp_7j

    tension_cfg = config["indicateurs"]["bilan_eau"]["tension_irrigation"]
    tension = (
        etp_24h > tension_cfg["seuil_etp_seche_mm"]
        and pluie_24h < tension_cfg["seuil_pluie_compense_mm"]
        and bilan_7j < tension_cfg["seuil_deficit_7j_mm"]
    )

    return IndicateursVeille(
        temperature_min_24h_celsius=float(temperature_celsius_24h.min()),
        temperature_max_24h_celsius=float(temperature_celsius_24h.max()),
        cumul_pluie_24h_mm=pluie_24h,
        cumul_pluie_48h_mm=float(h48["precipitation"].sum()),
        cumul_pluie_72h_mm=float(h72["precipitation"].sum()),
        vent_max_24h_kmh=float(h24["vitesse_vent_10m"].max() * MS_TO_KMH),
        rafales_max_24h_kmh=float(h24["rafales_vent_10m"].max() * MS_TO_KMH),
        etp_jour_mm=etp_24h,
        bilan_eau_7j_mm=bilan_7j,
        tension_irrigation=bool(tension),
    )
