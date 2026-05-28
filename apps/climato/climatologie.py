"""Calculs climatologiques pour l'App 3 — agrégations mensuelles, normales,
dates clés (premier/dernier gel), nombre de jours caractéristiques.

Cohérence inter-apps : l'ETP est calculée par le socle FAO Penman-Monteith
(cf. mémoire ``coherence-methode-inter-apps``), pas reprise du champ
``etp_open_meteo`` du fournisseur.
"""

from __future__ import annotations

import pandas as pd

from meteo_socle.indices.etp_fao import calcul_etp

KELVIN_OFFSET: float = 273.15

# Colonnes minimales nécessaires au calcul d'ETP socle.
_INPUTS_ETP = [
    "temperature_2m",
    "humidite_relative",
    "vitesse_vent_10m",
    "rayonnement_global",
]


def _avec_etp_socle(
    df_horaire: pd.DataFrame, latitude: float, longitude: float, altitude: float
) -> pd.DataFrame:
    """Ajoute la colonne ``etp_socle_mm`` calculée par le socle."""
    out = df_horaire.copy()
    out["etp_socle_mm"] = calcul_etp(out[_INPUTS_ETP], latitude, longitude, altitude)
    return out


def agreger_quotidien(
    df_horaire: pd.DataFrame, latitude: float, longitude: float, altitude: float
) -> pd.DataFrame:
    """Agrège la prévision horaire en valeurs quotidiennes (UTC).

    Colonnes : ``t_min_celsius``, ``t_max_celsius``, ``t_moy_celsius``,
    ``pluie_mm``, ``etp_mm``.
    """
    df = _avec_etp_socle(df_horaire, latitude, longitude, altitude)
    df["t_celsius"] = df["temperature_2m"] - KELVIN_OFFSET
    df["date"] = df.index.date
    quot = df.groupby("date").agg(
        t_min_celsius=("t_celsius", "min"),
        t_max_celsius=("t_celsius", "max"),
        t_moy_celsius=("t_celsius", "mean"),
        pluie_mm=("precipitation", "sum"),
        etp_mm=("etp_socle_mm", "sum"),
    )
    quot.index = pd.to_datetime(quot.index)
    quot.index.name = "date"
    return quot


def agreger_mensuel(quotidien: pd.DataFrame) -> pd.DataFrame:
    """Agrège les valeurs quotidiennes en mois × année.

    Index = MultiIndex ``(annee, mois)`` ; colonnes :
    ``t_min``, ``t_max``, ``t_moy``, ``pluie``, ``etp``.
    """
    df = quotidien.copy()
    df["annee"] = df.index.year
    df["mois"] = df.index.month
    return df.groupby(["annee", "mois"]).agg(
        t_min=("t_min_celsius", "mean"),
        t_max=("t_max_celsius", "mean"),
        t_moy=("t_moy_celsius", "mean"),
        pluie=("pluie_mm", "sum"),
        etp=("etp_mm", "sum"),
    )


def normale_mensuelle(mensuel: pd.DataFrame, periode: tuple[int, int]) -> pd.DataFrame:
    """Moyenne climatologique mensuelle sur la fenêtre ``(début, fin)`` (incluse).

    Returns
    -------
    pd.DataFrame
        Index = mois 1-12. Colonnes identiques à ``mensuel``.
    """
    debut, fin = periode
    years = mensuel.index.get_level_values("annee")
    mask = (years >= debut) & (years <= fin)
    return mensuel.loc[mask].groupby(level="mois").mean()


def jours_caracteristiques_par_annee(
    quotidien: pd.DataFrame,
    seuil_gel: float = 0.0,
    seuil_canicule: float = 30.0,
    seuil_jour_pluvieux: float = 10.0,
) -> pd.DataFrame:
    """Compte par année les jours dépassant les seuils.

    - ``jours_gel`` : T° min < seuil_gel
    - ``jours_canicule`` : T° max > seuil_canicule
    - ``jours_pluvieux`` : pluie 24h > seuil_jour_pluvieux
    """
    df = quotidien.copy()
    df["annee"] = df.index.year
    df["est_gel"] = df["t_min_celsius"] < seuil_gel
    df["est_canicule"] = df["t_max_celsius"] > seuil_canicule
    df["est_pluvieux"] = df["pluie_mm"] > seuil_jour_pluvieux
    return df.groupby("annee").agg(
        jours_gel=("est_gel", "sum"),
        jours_canicule=("est_canicule", "sum"),
        jours_pluvieux=("est_pluvieux", "sum"),
    )


def dates_gel_par_annee(quotidien: pd.DataFrame, seuil_gel: float = 0.0) -> pd.DataFrame:
    """Pour chaque année, date du dernier gel printanier et du premier gel
    automnal, et durée de saison sans gel.

    - Dernier gel printanier = dernière date entre janv. et juin avec
      T° min < seuil_gel.
    - Premier gel automnal = première date entre juil. et déc. avec
      T° min < seuil_gel.
    """
    df = quotidien.copy()
    df["annee"] = df.index.year
    df["mois"] = df.index.month
    df["est_gel"] = df["t_min_celsius"] < seuil_gel

    resultats: list[dict] = []
    for annee, sub in df.groupby("annee"):
        printemps = sub[(sub["mois"] <= 6) & sub["est_gel"]]
        automne = sub[(sub["mois"] >= 7) & sub["est_gel"]]
        dernier = printemps.index.max() if not printemps.empty else pd.NaT
        premier = automne.index.min() if not automne.empty else pd.NaT
        duree = (premier - dernier).days if pd.notna(dernier) and pd.notna(premier) else None
        resultats.append(
            {
                "annee": annee,
                "dernier_gel_printemps": dernier,
                "premier_gel_automne": premier,
                "saison_sans_gel_jours": duree,
            }
        )
    return pd.DataFrame(resultats).set_index("annee")
