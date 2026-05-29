"""Indicateurs de risque mildiou (socle).

Implémentation **Smith periods** (Smith 1956) pour la tomate sous abri
en climat tempéré humide océanique. Cf. ADR-0007 pour la justification
du choix de modèle et les hypothèses.

Définition opérationnelle (mise à jour 2026-05-29 — substitution proxy
humectation HR → LWD Gleason 1994 — cf. ADR-0005 et ADR-0007 *Mise à
jour* à venir) : une période de Smith est détectée sur deux jours
calendaires locaux *A* et *B* consécutifs si **les deux** satisfont :

- T_min ≥ 10 °C
- nb heures de **LWD CART Gleason** ≥ 11 h

L'entrée humectation n'est plus le simple compteur HR ≥ 90 % mais la
sortie du modèle CART Gleason 1994 (DPD, vent, HR, override pluie),
plus discriminant en climat océanique où l'HR nocturne est saturée
sans condensation effective.

Étiquette portée par le jour *B* (clôture).

Références : Smith, L.P., 1956. *Potato blight forecasting by 90 per
cent humidity criteria*. Plant Pathology 5, 83-87 (modèle Smith) ;
Gleason, M.L. et al., 1994. Plant Disease 78, 1011-1016 (proxy LWD).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from meteo_socle.indices.lwd_gleason import heures_lwd_par_jour

# Défauts Smith historiques (cf. ADR-0007). Paramétrables côté config
# pour réétalonnage local sans toucher au code.
SMITH_T_MIN_CELSIUS = 10.0
SMITH_HEURES_MIN = 11


@dataclass(frozen=True)
class CritereJournalierSmith:
    """Résultat journalier détaillé pour un seul jour calendaire local.

    Permet de présenter dans les apps *pourquoi* un jour qualifie
    (transparence — principe #5).
    """

    date: pd.Timestamp  # date locale (jour calendaire)
    t_min_celsius: float
    heures_humectation: int  # heures LWD CART Gleason
    qualifie: bool  # T_min ≥ seuil ET heures_humectation ≥ h_min


def agreger_critere_journalier(
    horaire: pd.DataFrame,
    tz_locale: str = "Europe/Paris",
) -> pd.DataFrame:
    """Agrège l'horaire en critère journalier Smith par jour local.

    L'humectation est désormais calculée par le modèle **CART Gleason
    1994** (cf. ``meteo_socle.indices.lwd_gleason``) à la place du
    simple compteur HR ≥ 90 %. Cohérent avec la décision LWD de
    l'ADR-0005.

    Parameters
    ----------
    horaire :
        DataFrame indexé UTC (conventions socle). Doit contenir
        ``temperature_2m`` (K), ``humidite_relative`` (fraction 0-1),
        ``vitesse_vent_10m`` (m/s) et ``precipitation`` (mm, optionnel).
    tz_locale :
        Fuseau pour découper les jours calendaires (défaut Europe/Paris).

    Returns
    -------
    pd.DataFrame
        Indexé par date locale (sans tz), colonnes :
        ``t_min_celsius`` et ``heures_humectation`` (LWD Gleason).
    """
    if horaire.empty:
        return pd.DataFrame(columns=["t_min_celsius", "heures_humectation"])

    # Agrégation LWD horaire → heures par jour local.
    lwd_quot = heures_lwd_par_jour(horaire, tz_locale=tz_locale)

    # T° min par jour local.
    horaire_loc = horaire.copy()
    idx_utc = pd.DatetimeIndex(horaire_loc.index)
    horaire_loc.index = idx_utc.tz_convert(tz_locale)
    t_celsius = horaire_loc["temperature_2m"] - 273.15
    t_min_quot = t_celsius.resample("D").min()
    t_min_quot.index = pd.DatetimeIndex(t_min_quot.index).tz_localize(None)

    quotidien = pd.DataFrame(
        {
            "t_min_celsius": t_min_quot,
            "heures_humectation": lwd_quot["heures_lwd"].reindex(t_min_quot.index, fill_value=0),
        }
    )
    quotidien.index.name = "date"
    return quotidien


def smith_periods(
    quotidien_critere: pd.DataFrame,
    t_min_celsius: float = SMITH_T_MIN_CELSIUS,
    heures_min: int = SMITH_HEURES_MIN,
) -> pd.Series:
    """Détecte les périodes de Smith dans une série quotidienne.

    Parameters
    ----------
    quotidien_critere :
        DataFrame issu de ``agreger_critere_journalier`` (colonnes
        ``t_min_celsius`` et ``heures_humectation``).
    t_min_celsius :
        Seuil T_min en °C (défaut 10.0).
    heures_min :
        Nb minimum d'heures d'humectation par jour (défaut 11 — seuil
        Smith historique, ré-utilisé sur l'input LWD Gleason).

    Returns
    -------
    pd.Series
        Série booléenne indexée par date locale (idem entrée). True
        sur le **jour B** d'une fenêtre A-B qualifiante. Le premier
        jour (sans veille observable) est toujours False.
    """
    qualifie = (quotidien_critere["t_min_celsius"] >= t_min_celsius) & (
        quotidien_critere["heures_humectation"] >= heures_min
    )
    veille_qualifie = qualifie.shift(1, fill_value=False)
    smith = qualifie & veille_qualifie
    smith.name = "smith_period"
    return smith


def nb_smith_periods_par_annee(smith: pd.Series) -> pd.Series:
    """Compte les périodes de Smith par année calendaire.

    Utilisé par l'App Climato pour caractériser la pression annuelle.

    Parameters
    ----------
    smith :
        Série booléenne ``smith_period`` indexée par date.

    Returns
    -------
    pd.Series
        Indexée par année (int), valeur = nombre de jours étiquetés
        "smith period" dans l'année.
    """
    if smith.empty:
        return pd.Series(dtype=int, name="nb_smith_periods")
    annees = pd.DatetimeIndex(smith.index).year
    return smith.astype(int).groupby(annees).sum().rename("nb_smith_periods")
