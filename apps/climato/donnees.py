"""Fetch des données historiques pour l'App 3 Climato.

Wrapper léger autour de ``OpenMeteoArchive`` qui :

- découpe la période demandée en lots annuels pour éviter les timeouts ;
- concatène les résultats en un DataFrame unique horaire indexé UTC.

Le cache disque est intentionnellement absent en v0 — chaque build
Quarto refait le fetch. À ajouter en v1 si les builds deviennent
lents.
"""

from __future__ import annotations

import pandas as pd

from meteo_socle.sources.openmeteo_archive import OpenMeteoArchive


def fetch_historique(
    latitude: float,
    longitude: float,
    annee_debut: int,
    annee_fin: int,
    modele: str = "era5_land",
    source: OpenMeteoArchive | None = None,
) -> pd.DataFrame:
    """Récupère l'historique horaire entre ``annee_debut`` et ``annee_fin`` (inclus).

    Découpé en lots annuels pour limiter la taille de chaque réponse
    HTTP (~3 Mo / an).

    Parameters
    ----------
    latitude, longitude :
        Site (degrés décimaux).
    annee_debut, annee_fin :
        Années bornes (incluses).
    modele :
        Modèle Open-Meteo archive (``"era5_land"`` par défaut).
    source :
        Client à utiliser. Injectable pour tests (mock).

    Returns
    -------
    pd.DataFrame
        DataFrame indexé UTC, colonnes socle.
    """
    if source is None:
        source = OpenMeteoArchive(modele=modele)
    lots = []
    for annee in range(annee_debut, annee_fin + 1):
        df = source.obtenir_historique(
            latitude=latitude,
            longitude=longitude,
            start_date=f"{annee}-01-01",
            end_date=f"{annee}-12-31",
        )
        lots.append(df)
    return pd.concat(lots).sort_index()
