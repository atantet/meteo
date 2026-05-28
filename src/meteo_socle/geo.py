import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree


# Rayon de la terre (km)
RAYON_TERRE_KM = 6371.

def conversion_latlon_rad(df_liste_stations, latlon_labels):
    '''Conversion de degrés en radians pour toutes les stations.'''
    df_latlon_rad = pd.DataFrame(index=df_liste_stations.index, dtype=float)
    for latlon_label, latlon_series in df_liste_stations[latlon_labels].items():
        df_latlon_rad.loc[:, f'{latlon_label}_rad'] = np.deg2rad(latlon_series)

    return df_latlon_rad

def calcul_arbre(df_liste_stations, latlon_labels):
    '''Calcul de l'arbre des stations les plus proches.'''
    df_latlon_rad = conversion_latlon_rad(df_liste_stations, latlon_labels)

    arbre = BallTree(df_latlon_rad, metric='haversine')

    return arbre

def selection_stations_plus_proches(
    df_liste_stations, ref_station_latlon, latlon_labels,
    nombre=None, rayon_km=None):
    
    arbre = calcul_arbre(df_liste_stations, latlon_labels)

    # Conversion de degrés en radians pour la référence
    ref_station_latlon_rad = np.deg2rad(ref_station_latlon)
    
    if nombre is not None:
        # Identification d'un certain nombre de stations les plus proches
        dist_rad_arr, ind_arr = arbre.query([ref_station_latlon_rad], k=nombre)
    elif rayon_km is not None:
        # Identification des stations les plus proches dans un certain rayon
        rayon_rad = rayon_km / RAYON_TERRE_KM
        ind_arr, dist_rad_arr = arbre.query_radius(
            [ref_station_latlon_rad], rayon_rad,
            count_only=False, return_distance=True, sort_results=True)

    dist_rad, ind = dist_rad_arr[0], ind_arr[0]

    # Conversion en km de la distance en rad
    dist_km = np.round(dist_rad * RAYON_TERRE_KM).astype(int)

    # Sélection des stations les plus proches
    df_liste_stations_nn = df_liste_stations.iloc[ind].copy()
    df_liste_stations_nn.loc[:, 'distance'] = dist_km
    
    return df_liste_stations_nn

def interpolation_inverse_distance_carre(df, s_dist_km):
    '''Interpolation des stations les plus proches pondérée par l'inverse de la distance au carré.'''
    # Calcul des poids à partir des distances
    poids = 1. / s_dist_km**2

    # Adaptation des dimensions des poids aux données météo
    df_piv = df.unstack()
    poids_piv = (df_piv + 1.e-6).mul(poids, axis='index') / (df_piv + 1.e-6)

    # Interpolation
    df_ref = ((df_piv * poids_piv).sum(0) / poids_piv.sum(0)).unstack().transpose()
    
    return df_ref