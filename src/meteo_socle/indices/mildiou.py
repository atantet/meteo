"""Indicateurs de risque mildiou (socle).

Implémentation **Smith periods** (Smith 1956) pour la tomate sous abri
en climat tempéré humide océanique. Cf. ADR-0007 pour la justification
du choix de modèle et les hypothèses.

Définition opérationnelle (rappel ADR-0007) : une période de Smith est
détectée sur deux jours calendaires locaux *A* et *B* consécutifs si
**les deux** satisfont :

- T_min ≥ 10 °C
- nb heures HR ≥ 90 % ≥ 11 h

Étiquette portée par le jour *B* (clôture).

Référence : Smith, L.P., 1956. *Potato blight forecasting by 90 per
cent humidity criteria*. Plant Pathology 5, 83-87.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Défauts Smith historiques (cf. ADR-0007). Paramétrables côté config
# pour réétalonnage local sans toucher au code.
SMITH_T_MIN_CELSIUS = 10.0
SMITH_HR_SEUIL = 0.90  # fraction (HR socle en 0-1)
SMITH_HEURES_MIN = 11


@dataclass(frozen=True)
class CritereJournalierSmith:
    """Résultat journalier détaillé pour un seul jour calendaire local.

    Permet de présenter dans les apps *pourquoi* un jour qualifie
    (transparence — principe #5).
    """

    date: pd.Timestamp  # date locale (jour calendaire)
    t_min_celsius: float
    heures_hr_haute: int
    qualifie: bool  # T_min ≥ seuil ET heures_hr_haute ≥ h_min


def agreger_critere_journalier(
    horaire: pd.DataFrame,
    tz_locale: str = "Europe/Paris",
    hr_seuil: float = SMITH_HR_SEUIL,
) -> pd.DataFrame:
    """Agrège l'horaire en critère journalier Smith par jour local.

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
        ``t_min_celsius``, ``heures_hr_haute``.
    """
    if horaire.empty:
        return pd.DataFrame(columns=["t_min_celsius", "heures_hr_haute"])

    horaire_loc = horaire.copy()
    idx_utc = pd.DatetimeIndex(horaire_loc.index)
    horaire_loc.index = idx_utc.tz_convert(tz_locale)

    t_celsius = horaire_loc["temperature_2m"] - 273.15
    hr = horaire_loc["humidite_relative"]
    hr_haute = (hr >= hr_seuil).astype(int)

    quotidien = pd.DataFrame(
        {
            "t_min_celsius": t_celsius.resample("D").min(),
            "heures_hr_haute": hr_haute.resample("D").sum(),
        }
    )
    # Index sans tz pour un usage commode (date pure).
    quotidien.index = pd.DatetimeIndex(quotidien.index).tz_localize(None)
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
        ``t_min_celsius`` et ``heures_hr_haute``).
    t_min_celsius :
        Seuil T_min en °C (défaut 10.0).
    heures_min :
        Nb minimum d'heures HR ≥ seuil (défaut 11).

    Returns
    -------
    pd.Series
        Série booléenne indexée par date locale (idem entrée). True
        sur le **jour B** d'une fenêtre A-B qualifiante. Le premier
        jour (sans veille observable) est toujours False.
    """
    qualifie = (quotidien_critere["t_min_celsius"] >= t_min_celsius) & (
        quotidien_critere["heures_hr_haute"] >= heures_min
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
