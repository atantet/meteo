"""Fetch et cache des données historiques pour l'App 3 Climato.

Deux entrées :

- ``fetch_historique`` : appelle Open-Meteo Archive (1 requête par
  année, ~10 s/an). Utilisé par le script de refresh du cache.
- ``charger_historique_cache`` : lit le parquet versionné
  ``data/climato/historique_horaire.parquet``. Utilisé par le rapport
  Quarto pour un build rapide (<1 min vs 7-10 min de fetch direct).

Le refresh du cache est piloté par ``scripts/refresh_cache_climato.py``
et le workflow ``.github/workflows/refresh-climato-cache.yml`` (cron
mensuel + dispatch manuel).
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from meteo_socle.sources.openmeteo_archive import OpenMeteoArchive

# Chemin canonique du cache (relatif à la racine du repo).
CACHE_PATH = Path("data/climato/historique_horaire.parquet")


def fetch_historique(
    latitude: float,
    longitude: float,
    annee_debut: int,
    annee_fin: int,
    modele: str = "era5_land",
    source: OpenMeteoArchive | None = None,
    delai_entre_lots_s: float = 1.0,
) -> pd.DataFrame:
    """Récupère l'historique horaire entre ``annee_debut`` et ``annee_fin`` (inclus).

    Découpé en lots annuels pour limiter la taille de chaque réponse
    HTTP (~3 Mo / an). Un délai entre lots évite les rate-limits 429
    sur de longues fenêtres (30 ans normale OMM par ex.).

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
    delai_entre_lots_s :
        Délai en secondes inséré entre chaque appel annuel. Mettre à 0
        pour les tests.

    Returns
    -------
    pd.DataFrame
        DataFrame indexé UTC, colonnes socle.
    """
    if source is None:
        source = OpenMeteoArchive(modele=modele)
    lots = []
    annees = list(range(annee_debut, annee_fin + 1))
    for i, annee in enumerate(annees):
        df = source.obtenir_historique(
            latitude=latitude,
            longitude=longitude,
            start_date=f"{annee}-01-01",
            end_date=f"{annee}-12-31",
        )
        lots.append(df)
        # Pause entre lots sauf après le dernier.
        if delai_entre_lots_s > 0 and i < len(annees) - 1:
            time.sleep(delai_entre_lots_s)
    return pd.concat(lots).sort_index()


def charger_historique_cache(
    repo_root: Path | None = None,
    annee_debut: int | None = None,
    annee_fin: int | None = None,
) -> pd.DataFrame:
    """Charge l'historique horaire depuis le parquet cache versionné.

    Parameters
    ----------
    repo_root :
        Racine du repo (où se trouve ``data/climato/…``). Si None,
        cherche en remontant depuis le cwd jusqu'à trouver le dossier
        ``data/climato``.
    annee_debut, annee_fin :
        Filtres optionnels sur l'année (inclus). Permet à un build
        local de ne charger qu'une sous-fenêtre du cache 30 ans.

    Returns
    -------
    pd.DataFrame
        DataFrame indexé UTC, colonnes socle.

    Raises
    ------
    FileNotFoundError
        Si le cache n'existe pas. Indique au lecteur comment le générer.
    """
    if repo_root is None:
        repo_root = Path.cwd().resolve()
        while repo_root != repo_root.parent and not (repo_root / CACHE_PATH).exists():
            repo_root = repo_root.parent
    chemin = repo_root / CACHE_PATH
    if not chemin.exists():
        raise FileNotFoundError(
            f"Cache climato introuvable : {chemin}. "
            "Le générer avec `python scripts/refresh_cache_climato.py`."
        )
    df = pd.read_parquet(chemin)
    if annee_debut is not None:
        df = df[df.index.year >= annee_debut]
    if annee_fin is not None:
        df = df[df.index.year <= annee_fin]
    return df
