"""Indicateurs quotidiens agrégés pour l'App 2 Opérationnelle.

À partir d'une prévision horaire (sortie ``OpenMeteoForecast``) sur
3-14 jours, produit un DataFrame indexé par date (TZ locale) avec
les colonnes nécessaires à la vue Semaine :

- ``t_min_celsius`` : T° min de la journée locale (proxy nuit).
- ``t_max_celsius`` : T° max de la journée locale (proxy jour).
- ``pluie_24h_mm`` : cumul de précipitation sur la journée locale.
- ``rafales_max_kmh`` : rafales max prévues sur la journée locale.
- ``etp_mm`` : ETP cumulée (FAO socle, cf. principe cohérence).
- ``bilan_eau_cumul_mm`` : (pluie − ETP) cumulé depuis le 1er jour
  de la fenêtre.

Le découpage "journée locale" se fait via la TZ ``site.tz`` (par défaut
Europe/Paris) pour aligner les jours sur le ressenti utilisateur.

Cohérence inter-apps (cf. mémoire ``coherence-methode-inter-apps``) :
l'ETP est calculée par ``meteo_socle.indices.etp_fao.calcul_etp``, pas
reprise du champ ``etp_open_meteo`` du fournisseur.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from meteo_socle.indices.etp_fao import calcul_etp

# Conversions vers unités de présentation utilisateur.
KELVIN_OFFSET: float = 273.15
MS_TO_KMH: float = 3.6

# Colonnes d'entrée nécessaires au calcul d'ETP socle.
_INPUTS_ETP = [
    "temperature_2m",
    "humidite_relative",
    "vitesse_vent_10m",
    "rayonnement_global",
]

# Référence climato (cf. apps/veille/charts.py — même fichier réutilisé).
NORMALE_JOUR_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "climato" / "normale_jour_lapetiteclaye.csv"
)

# Conversion direction (degrés) → secteur cardinal (cf. apps.veille.indicateurs).
CARDINAUX = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


def _degrees_to_cardinal(deg: float) -> str:
    if np.isnan(deg):
        return ""
    idx = int(round((deg % 360) / 45)) % 8
    return CARDINAUX[idx]


def _direction_dominante_vecteur(group: pd.DataFrame) -> float:
    """Moyenne vectorielle pondérée vitesse pour un groupe (1 jour)."""
    if "direction_vent_deg" not in group.columns:
        return float("nan")
    s = group["direction_vent_deg"].dropna()
    if s.empty:
        return float("nan")
    rad = np.deg2rad(s)
    poids = group.loc[s.index, "vitesse_vent_10m"] if "vitesse_vent_10m" in group else 1.0
    u = -poids * np.sin(rad)
    v = -poids * np.cos(rad)
    return float(np.rad2deg(np.arctan2(-u.mean(), -v.mean())) % 360)


def _charger_normale_t_moy() -> pd.Series | None:
    if not NORMALE_JOUR_PATH.exists():
        return None
    try:
        df = pd.read_csv(NORMALE_JOUR_PATH)
        return df.set_index("day_of_year")["t_moy_celsius"]
    except (OSError, KeyError):
        return None


def _charger_normales_journalieres() -> pd.DataFrame | None:
    """Charge t_min / t_max / t_moy normales par day-of-year."""
    if not NORMALE_JOUR_PATH.exists():
        return None
    try:
        df = pd.read_csv(NORMALE_JOUR_PATH)
        return df.set_index("day_of_year")[["t_min_celsius", "t_max_celsius", "t_moy_celsius"]]
    except (OSError, KeyError):
        return None


def calculer_indicateurs_quotidiens(
    prevision: pd.DataFrame,
    config: dict[str, Any],
    now_utc: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Agrège la prévision horaire en valeurs quotidiennes en TZ locale.

    Parameters
    ----------
    prevision :
        DataFrame indexé tz-aware UTC, colonnes selon les conventions
        socle (cf. ``OpenMeteoForecast``).
    config :
        Configuration App 2 (``site`` requis pour ETP et TZ locale).
    now_utc :
        Si fourni, les lignes antérieures sont écartées. Sinon, on
        garde tout (utile pour preview historique).

    Returns
    -------
    pd.DataFrame
        Indexé par date (``DatetimeIndex`` daily TZ locale), colonnes :
        t_min_celsius, t_max_celsius, pluie_24h_mm, rafales_max_kmh,
        etp_mm, bilan_eau_cumul_mm.
    """
    df = prevision.copy()
    if now_utc is not None:
        df = df.loc[df.index >= now_utc]
    if df.empty:
        raise ValueError("Prévision vide après filtre now_utc.")
    df = df.sort_index()

    site = config["site"]
    # ADR-0011 D5 : agrégation quotidienne par jour UTC (cohérence tout-UTC
    # avec la grille tendance et la Veille ; le fuseau du site ne sert plus au
    # binning temporel, seulement à la géoloc pour l'ETP).
    tz_locale = "UTC"

    # ETP horaire via socle, sur l'ensemble de la fenêtre.
    etp_horaire = calcul_etp(df[_INPUTS_ETP], site["latitude"], site["longitude"], site["altitude"])

    # Conversion en unités utilisateur + index local pour groupby par
    # date locale.
    travail = pd.DataFrame(index=df.index)
    travail["t_celsius"] = df["temperature_2m"] - KELVIN_OFFSET
    travail["pluie_mm"] = df["precipitation"]
    travail["rafales_kmh"] = df["rafales_vent_10m"] * MS_TO_KMH
    travail["vitesse_vent_kmh"] = df["vitesse_vent_10m"] * MS_TO_KMH
    travail["etp_mm"] = etp_horaire
    if "probabilite_pluie_pct" in df.columns:
        travail["probabilite_pluie_pct"] = df["probabilite_pluie_pct"]

    # Stocke aussi vitesse + direction pour la direction dominante
    # journalière calculée plus bas.
    travail["vitesse_vent_10m"] = df["vitesse_vent_10m"]
    if "direction_vent_deg" in df.columns:
        travail["direction_vent_deg"] = df["direction_vent_deg"]

    travail.index = travail.index.tz_convert(tz_locale)
    travail["date_locale"] = travail.index.date

    agg_dict = {
        "t_min_celsius": ("t_celsius", "min"),
        "t_max_celsius": ("t_celsius", "max"),
        "t_moy_celsius": ("t_celsius", "mean"),
        "pluie_24h_mm": ("pluie_mm", "sum"),
        "rafales_max_kmh": ("rafales_kmh", "max"),
        "vent_moy_kmh": ("vitesse_vent_kmh", "mean"),
        "etp_mm": ("etp_mm", "sum"),
    }
    if "probabilite_pluie_pct" in travail.columns:
        agg_dict["prob_pluie_max_pct"] = ("probabilite_pluie_pct", "max")
    quotidien = travail.groupby("date_locale").agg(**agg_dict)

    # Direction dominante par jour (vector mean pondéré vitesse).
    if "direction_vent_deg" in travail.columns:
        dirs_jour = travail.groupby("date_locale").apply(
            _direction_dominante_vecteur, include_groups=False
        )
        quotidien["direction_vent_deg"] = dirs_jour.reindex(quotidien.index).values
        quotidien["direction_vent_cardinal"] = quotidien["direction_vent_deg"].map(
            _degrees_to_cardinal
        )

    quotidien["bilan_eau_cumul_mm"] = (quotidien["pluie_24h_mm"] - quotidien["etp_mm"]).cumsum()

    # Le risque maladie n'est plus un indicateur Smith mildiou (humectation
    # abandonnée) mais un guide « nuit douce » (T° min ≥ seuil) construit en aval
    # depuis t_min_celsius — cf. decisions.regle_risque_maladie.

    # Climato T° normales OMM 1991-2020 (cf. data/climato/normale_jour_*.csv).
    normales = _charger_normales_journalieres()
    if normales is not None:
        doy = pd.to_datetime(quotidien.index).dayofyear
        quotidien["t_min_normale_celsius"] = normales["t_min_celsius"].reindex(doy).values
        quotidien["t_max_normale_celsius"] = normales["t_max_celsius"].reindex(doy).values
        quotidien["t_moy_normale_celsius"] = normales["t_moy_celsius"].reindex(doy).values
        quotidien["ecart_normale_celsius"] = (
            quotidien["t_moy_celsius"] - quotidien["t_moy_normale_celsius"]
        )

    quotidien.index = pd.to_datetime(quotidien.index)
    quotidien.index.name = "date"
    return quotidien


def jours_complets_seulement(df: pd.DataFrame, prevision: pd.DataFrame) -> pd.DataFrame:
    """Filtre les jours partiels (premier ou dernier jour incomplet).

    Un jour est "complet" si la prévision couvre au moins 23 h des
    24 h de ce jour en TZ locale. Évite d'afficher un "T° max 18 °C"
    sur un jour où l'on n'a que les 6 heures du matin.

    Parameters
    ----------
    df :
        Sortie de ``calculer_indicateurs_quotidiens``.
    prevision :
        Prévision horaire originale (pour mesurer la couverture).
    """
    if df.empty:
        return df
    tz = df.index.tz if df.index.tz is not None else "UTC"
    prev_local = prevision.tz_convert(tz)
    couverture = prev_local.groupby(prev_local.index.date).size()
    couverture.index = pd.to_datetime(couverture.index)
    # Aligne sur l'index `df` (re-index avec fill_value=0 sur les
    # dates absentes de la couverture, puis filtre booléen).
    couverture = couverture.reindex(df.index, fill_value=0)
    return df.loc[couverture >= 23]
