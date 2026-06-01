"""Préparation des séries temporelles horaires de l'App 2 §4.

Fournit un DataFrame horaire prêt pour le rendu des courbes par
indicateur (`figure_indicateur`). Granularité horaire (au lieu du
quotidien qui ne fait que 4 points sur 4 j) : le cycle diurne devient
visible, et le contexte 48 h passées (ERA5) peut être ajouté en amont.

Variables disponibles dans le DataFrame retourné :

- ``temperature_2m_c``      : T° instantanée en °C (K → °C)
- ``precipitation``         : pluie horaire (mm/h)
- ``etp_horaire_mm``        : ET₀ FAO socle (mm/h)
- ``bilan_eau_horaire_mm``  : pluie − ET₀ (mm/h)
- ``bilan_eau_cumul_mm``    : cumul depuis le début de la série (mm)
- ``rafales_max_kmh``       : rafales (m/s → km/h)
- ``vent_moy_kmh``          : vent moyen (m/s → km/h)
- ``humidite_relative``     : HR en fraction 0-1

Convention origine : la 1ʳᵉ ligne du DataFrame ouvre la fenêtre
visualisable (donc l'origine du cumul de bilan eau). Quand on inclut
ERA5 sur les 48 h passées, le cumul démarre J-2 00:00, ce qui fait
voir l'historique récent du bilan en amont de la prévision.
"""

from __future__ import annotations

import pandas as pd

from apps.operationnelle.charts import CourbeConfig
from meteo_socle.indices.etp_fao import calcul_etp

KELVIN_VERS_CELSIUS = 273.15
MS_VERS_KMH = 3.6

# Colonnes socle nécessaires au calcul ETP (cf. `apps.operationnelle.indicateurs`).
_INPUTS_ETP = (
    "temperature_2m",
    "humidite_relative",
    "vitesse_vent_10m",
    "rayonnement_global",
)


def etp_horaire_socle(horaire: pd.DataFrame, site: dict) -> pd.Series | None:
    """ETP socle FAO Penman-Monteith (mm/h), None si entrées manquantes.

    Force le cast float sur les colonnes d'entrée : un DataFrame issu de
    `pd.concat` (ex. ERA5 + forecast) peut avoir des dtypes `object`
    quand les colonnes diffèrent entre les morceaux, ce qui fait échouer
    `np.exp` dans `calcul_etp` (TypeError « loop of ufunc »).
    """
    if not all(c in horaire.columns for c in _INPUTS_ETP):
        return None
    inputs = horaire[list(_INPUTS_ETP)].apply(pd.to_numeric, errors="coerce")
    try:
        return calcul_etp(
            inputs,
            site["latitude"],
            site["longitude"],
            site["altitude"],
        )
    except (KeyError, ValueError):
        return None


def preparer_horaire(
    prevision: pd.DataFrame,
    site: dict,
    passe: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Construit le DataFrame horaire des courbes.

    Concatène ``passe`` (ERA5, optionnel) puis ``prevision`` (ARPEGE),
    convertit les unités d'affichage (K → °C, m/s → km/h), calcule ET₀
    socle horaire et le bilan eau cumul depuis l'origine.

    Parameters
    ----------
    prevision :
        DataFrame horaire tz-aware UTC (sortie `OpenMeteoForecast`).
    site :
        Dict avec ``latitude``, ``longitude``, ``altitude`` (config Op).
    passe :
        DataFrame ERA5 sur 24-48 h passées, format identique.
        Si fourni, est concaténé en amont de la prévision.

    Returns
    -------
    pd.DataFrame
        Indexé tz-aware UTC, croissant, dédupliqué (en cas de recouvrement
        ERA5/forecast on garde la valeur ERA5 considérée comme « observée »).
    """
    morceaux = []
    if passe is not None and not passe.empty:
        morceaux.append(passe)
    morceaux.append(prevision)
    horaire = pd.concat(morceaux).sort_index()
    # Si recouvrement (ERA5 J-1 23:00 ↔ forecast J0 00:00 par exemple),
    # on garde la 1ʳᵉ occurrence (ERA5 prioritaire = passé observé).
    horaire = horaire[~horaire.index.duplicated(keep="first")]
    # Force le cast float : `pd.concat` entre deux DataFrames hétérogènes
    # (ERA5 sans toutes les colonnes vs forecast complet) peut produire
    # des colonnes en dtype `object`, qui font ensuite échouer les
    # ufuncs numpy de `calcul_etp` ("loop of ufunc does not support
    # argument 0 of type float which has no callable exp method").
    for col in horaire.columns:
        horaire[col] = pd.to_numeric(horaire[col], errors="coerce")

    out = pd.DataFrame(index=horaire.index)
    if "temperature_2m" in horaire.columns:
        out["temperature_2m_c"] = horaire["temperature_2m"] - KELVIN_VERS_CELSIUS
    if "precipitation" in horaire.columns:
        out["precipitation"] = horaire["precipitation"]
    if "vitesse_vent_10m" in horaire.columns:
        out["vent_moy_kmh"] = horaire["vitesse_vent_10m"] * MS_VERS_KMH
    if "rafales_vent_10m" in horaire.columns:
        out["rafales_max_kmh"] = horaire["rafales_vent_10m"] * MS_VERS_KMH
    if "humidite_relative" in horaire.columns:
        out["humidite_relative"] = horaire["humidite_relative"]

    etp = etp_horaire_socle(horaire, site)
    if etp is not None:
        out["etp_horaire_mm"] = etp.reindex(out.index)

    if "precipitation" in out.columns and "etp_horaire_mm" in out.columns:
        out["bilan_eau_horaire_mm"] = out["precipitation"] - out["etp_horaire_mm"]
        out["bilan_eau_cumul_mm"] = out["bilan_eau_horaire_mm"].cumsum()

    return out


# Courbes pour la résolution horaire — superset de couleurs cohérentes
# avec la grille tendance §1 et le mail Veille.
COURBES_HORAIRES: list[CourbeConfig] = [
    CourbeConfig(
        colonne="temperature_2m_c",
        titre="Température (horaire)",
        unite="°C",
        couleur="#D55E00",
    ),
    CourbeConfig(
        colonne="precipitation",
        titre="Pluie horaire",
        unite="mm/h",
        couleur="#56B4E9",
    ),
    CourbeConfig(
        colonne="etp_horaire_mm",
        titre="ET₀ horaire (FAO socle)",
        unite="mm/h",
        couleur="#009E73",
    ),
    CourbeConfig(
        colonne="bilan_eau_cumul_mm",
        titre="Bilan eau cumulé (pluie − ET₀)",
        unite="mm",
        couleur="#8e44ad",
    ),
    CourbeConfig(
        colonne="rafales_max_kmh",
        titre="Rafales (horaire)",
        unite="km/h",
        couleur="#E69F00",
    ),
]
