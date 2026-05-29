"""Indicateurs de risque mildiou (socle).

Implémentation **Smith periods** (Smith 1956) pour la tomate sous abri
en climat tempéré humide océanique. Cf. ADR-0007 pour la justification
du choix de modèle et les hypothèses.

Définition opérationnelle (rollback 2026-05-29 — cf. ADR-0010) :
le proxy d'humectation est **HR ≥ 90 %** (Smith historique), pas
LWD Gleason. La substitution éphémère vers LWD Gleason 1994 testée
ce jour a produit 5× plus de périodes Smith (84/an au lieu de 17/an
typiques Bretagne) faute d'adaptation de Gleason au climat océanique
humide. Décision : revenir à Smith dans sa forme calibrée terrain
UK 1956, garder LWD Gleason comme indicateur d'inspection visuelle
seulement (cf. ADR-0010 et la section climato comparative).

Une période de Smith est détectée sur deux jours calendaires locaux
*A* et *B* consécutifs si **les deux** satisfont :

- T_min ≥ 10 °C
- nb heures HR ≥ 90 % ≥ 11 h

Étiquette portée par le jour *B* (clôture).

Référence : Smith, L.P., 1956. *Potato blight forecasting by 90 per
cent humidity criteria*. Plant Pathology 5, 83-87.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Défauts Smith historiques (cf. ADR-0007 et ADR-0010).
SMITH_T_MIN_CELSIUS = 10.0
SMITH_HR_SEUIL = 0.90  # fraction (HR socle 0-1)
SMITH_HEURES_MIN = 11


@dataclass(frozen=True)
class CritereJournalierSmith:
    """Résultat journalier détaillé pour un seul jour calendaire local.

    Permet de présenter dans les apps *pourquoi* un jour qualifie
    (transparence — principe #5).
    """

    date: pd.Timestamp  # date locale (jour calendaire)
    t_min_celsius: float
    heures_humectation: int  # heures HR ≥ seuil (proxy Smith historique)
    qualifie: bool  # T_min ≥ seuil ET heures_humectation ≥ h_min


def agreger_critere_journalier(
    horaire: pd.DataFrame,
    tz_locale: str = "Europe/Paris",
    hr_seuil: float = SMITH_HR_SEUIL,
) -> pd.DataFrame:
    """Agrège l'horaire en critère journalier Smith par jour local.

    Le proxy d'humectation est le compteur **HR ≥ hr_seuil** (Smith
    historique 1956 — cf. ADR-0010 pour la doctrine pragmatique).

    Parameters
    ----------
    horaire :
        DataFrame indexé UTC (conventions socle). Doit contenir
        ``temperature_2m`` (K) et ``humidite_relative`` (fraction 0-1).
    tz_locale :
        Fuseau pour découper les jours calendaires (défaut Europe/Paris).
    hr_seuil :
        Seuil HR fraction (défaut 0.90).

    Returns
    -------
    pd.DataFrame
        Indexé par date locale (sans tz), colonnes :
        ``t_min_celsius`` et ``heures_humectation``.
    """
    if horaire.empty:
        return pd.DataFrame(columns=["t_min_celsius", "heures_humectation"])

    horaire_loc = horaire.copy()
    idx_utc = pd.DatetimeIndex(horaire_loc.index)
    horaire_loc.index = idx_utc.tz_convert(tz_locale)

    t_celsius = horaire_loc["temperature_2m"] - 273.15
    hr_haute = (horaire_loc["humidite_relative"] >= hr_seuil).astype(int)

    t_min_quot = t_celsius.resample("D").min()
    heures_quot = hr_haute.resample("D").sum()
    t_min_quot.index = pd.DatetimeIndex(t_min_quot.index).tz_localize(None)
    heures_quot.index = pd.DatetimeIndex(heures_quot.index).tz_localize(None)

    # Construction défensive (pas dict-literal — instabilité observée
    # avec pandas/numpy pré-release Python 3.14 sur Cloud).
    quotidien = pd.DataFrame(index=t_min_quot.index)
    quotidien["t_min_celsius"] = t_min_quot.to_numpy()
    quotidien["heures_humectation"] = heures_quot.reindex(t_min_quot.index, fill_value=0).to_numpy()
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
        Nb minimum d'heures d'humectation par jour (défaut 11, seuil
        Smith historique calibré sur HR ≥ 90 % UK 1956).

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
