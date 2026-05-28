"""Sélection et agrégation spatiale multi-station.

Implémente le principe transverse n°7 d'agrégation multi-station pour
les variables d'observation (cf. principes de conception du projet) :

1. **Sélection** des N stations les plus proches d'un site de référence
   (ou de toutes les stations dans un rayon donné), par recherche
   `BallTree` avec métrique haversine sur (latitude, longitude) en
   radians.
2. **Interpolation** des séries de valeurs depuis les stations
   sélectionnées vers le site de référence, pondérée par
   l'**inverse de la distance au carré** (IDW², Shepard 1968).

Référence pour la métrique haversine et le BallTree :
scikit-learn, `sklearn.neighbors.BallTree`,
<https://scikit-learn.org/stable/modules/generated/sklearn.neighbors.BallTree.html>.

Référence IDW² : Shepard, D., 1968. *A two-dimensional interpolation
function for irregularly-spaced data*. Proc. ACM Natl. Conf., 517-524.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

# Rayon moyen de la terre (km), valeur OMM standard.
RAYON_TERRE_KM: float = 6371.0


def conversion_latlon_rad(
    df_liste_stations: pd.DataFrame, latlon_labels: list[str]
) -> pd.DataFrame:
    """Convertit en radians les colonnes lat/lon d'un DataFrame stations.

    Parameters
    ----------
    df_liste_stations :
        DataFrame indexé par identifiant de station avec au moins les
        colonnes ``latlon_labels``.
    latlon_labels :
        Liste de 2 noms de colonnes (latitude, longitude) en degrés
        décimaux. Suffixées `_rad` dans la sortie.
    """
    df_latlon_rad = pd.DataFrame(index=df_liste_stations.index, dtype=float)
    for latlon_label, latlon_series in df_liste_stations[latlon_labels].items():
        df_latlon_rad.loc[:, f"{latlon_label}_rad"] = np.deg2rad(latlon_series)
    return df_latlon_rad


def calcul_arbre(
    df_liste_stations: pd.DataFrame, latlon_labels: list[str]
) -> BallTree:
    """Construit un `BallTree` haversine pour requêtes spatiales rapides."""
    df_latlon_rad = conversion_latlon_rad(df_liste_stations, latlon_labels)
    return BallTree(df_latlon_rad, metric="haversine")


def selection_stations_plus_proches(
    df_liste_stations: pd.DataFrame,
    ref_station_latlon: np.ndarray,
    latlon_labels: list[str],
    nombre: int | None = None,
    rayon_km: float | None = None,
) -> pd.DataFrame:
    """Sélectionne les stations les plus proches d'un site de référence.

    Deux modes mutuellement exclusifs :

    - ``nombre=N`` : N stations les plus proches, triées par distance.
    - ``rayon_km=R`` : toutes les stations dans un rayon de R km du
      site de référence, triées par distance.

    Parameters
    ----------
    df_liste_stations :
        DataFrame de stations indexé par identifiant.
    ref_station_latlon :
        Coordonnées du site de référence en degrés décimaux
        ``[lat, lon]``.
    latlon_labels :
        Noms des colonnes (latitude, longitude) dans
        ``df_liste_stations``.
    nombre :
        Mode "N plus proches".
    rayon_km :
        Mode "dans rayon R km".

    Returns
    -------
    pd.DataFrame
        Sous-ensemble de ``df_liste_stations`` ordonné par distance,
        avec une colonne ``distance`` (km, entiers arrondis).
    """
    arbre = calcul_arbre(df_liste_stations, latlon_labels)

    # Conversion de degrés en radians pour la référence.
    ref_station_latlon_rad = np.deg2rad(ref_station_latlon)

    if nombre is not None:
        dist_rad_arr, ind_arr = arbre.query([ref_station_latlon_rad], k=nombre)
    elif rayon_km is not None:
        rayon_rad = rayon_km / RAYON_TERRE_KM
        ind_arr, dist_rad_arr = arbre.query_radius(
            [ref_station_latlon_rad],
            rayon_rad,
            count_only=False,
            return_distance=True,
            sort_results=True,
        )
    else:
        raise ValueError("Préciser nombre ou rayon_km.")

    dist_rad, ind = dist_rad_arr[0], ind_arr[0]

    # Conversion radian → km (arrondi entier — précision opérationnelle
    # cohérente avec les sources d'erreur d'interpolation).
    dist_km = np.round(dist_rad * RAYON_TERRE_KM).astype(int)

    df_liste_stations_nn = df_liste_stations.iloc[ind].copy()
    df_liste_stations_nn.loc[:, "distance"] = dist_km
    return df_liste_stations_nn


def interpolation_inverse_distance_carre(
    df: pd.DataFrame, s_dist_km: pd.Series
) -> pd.DataFrame:
    """Interpolation inverse-distance² des valeurs aux stations vers le site.

    Implémente l'IDW² de Shepard (1968). Les poids sont 1/d² (distance
    en km), normalisés par la somme des poids effectivement utilisés
    pour chaque (variable, instant) — gestion naturelle des valeurs
    manquantes : si une station n'a pas de valeur, son poids n'entre
    pas dans la normalisation.

    Parameters
    ----------
    df :
        DataFrame en format long, indexé par MultiIndex
        ``(station, time)`` avec colonnes de variables météo.
    s_dist_km :
        Distances stations → site de référence (km), indexée par
        station.

    Returns
    -------
    pd.DataFrame
        Valeurs interpolées au site de référence, indexées par
        ``time``, colonnes = variables d'entrée.
    """
    # Poids 1 / d² (km⁻²).
    poids = 1.0 / s_dist_km**2

    # Adaptation des dimensions des poids aux données météo. Le terme
    # 1e-6 a deux fonctions : (i) éviter une division par zéro si une
    # variable a des valeurs nulles ; (ii) propager naturellement les
    # NaN (un NaN dans df_piv reste un NaN dans poids_piv après
    # division).
    df_piv = df.unstack()
    poids_piv = (df_piv + 1.0e-6).mul(poids, axis="index") / (df_piv + 1.0e-6)

    # Moyenne pondérée IDW². `axis=0` explicite cf. Pandas 4.0 (sum
    # devient keyword-only).
    return (
        ((df_piv * poids_piv).sum(axis=0) / poids_piv.sum(axis=0))
        .unstack()
        .transpose()
    )
