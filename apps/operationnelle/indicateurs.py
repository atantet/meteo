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

from typing import Any

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
    tz_locale = site.get("tz", "Europe/Paris")

    # ETP horaire via socle, sur l'ensemble de la fenêtre.
    etp_horaire = calcul_etp(df[_INPUTS_ETP], site["latitude"], site["longitude"], site["altitude"])

    # Conversion en unités utilisateur + index local pour groupby par
    # date locale.
    travail = pd.DataFrame(index=df.index)
    travail["t_celsius"] = df["temperature_2m"] - KELVIN_OFFSET
    travail["pluie_mm"] = df["precipitation"]
    travail["rafales_kmh"] = df["rafales_vent_10m"] * MS_TO_KMH
    travail["etp_mm"] = etp_horaire

    travail.index = travail.index.tz_convert(tz_locale)
    travail["date_locale"] = travail.index.date

    quotidien = travail.groupby("date_locale").agg(
        t_min_celsius=("t_celsius", "min"),
        t_max_celsius=("t_celsius", "max"),
        pluie_24h_mm=("pluie_mm", "sum"),
        rafales_max_kmh=("rafales_kmh", "max"),
        etp_mm=("etp_mm", "sum"),
    )

    quotidien["bilan_eau_cumul_mm"] = (quotidien["pluie_24h_mm"] - quotidien["etp_mm"]).cumsum()

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
