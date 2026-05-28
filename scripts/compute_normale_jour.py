"""Pré-calcul de la normale climatologique journalière pour le site Veille.

Récupère 10 ans d'ERA5 via Open-Meteo Archive, agrège en quotidien
(T_min, T_max, T_moy), puis moyenne par jour-de-l'année → 366 valeurs.

Sauve le CSV de référence ``data/climato/normale_jour_lapetiteclaye.csv``
versionné dans le repo et utilisé en overlay par
``apps.veille.charts.graphique_72h_base64``.

USAGE
=====

À exécuter ponctuellement (rare — pas dans le cron Veille) :

    ~/.conda/envs/meteo/bin/python scripts/compute_normale_jour.py

Coût : ~30-60 s (10 requêtes Open-Meteo annuelles).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from apps.climato.climatologie import agreger_quotidien  # noqa: E402
from apps.climato.config import load_config  # noqa: E402
from apps.climato.donnees import fetch_historique  # noqa: E402

OUTPUT_CSV = REPO_ROOT / "data" / "climato" / "normale_jour_lapetiteclaye.csv"


def main() -> None:
    config = load_config()
    site = config["site"]
    periode = config["rapport"]["periode_donnees"]
    modele = config["source_meteo"]["modele"]

    print(
        f"Fetch ERA5 ({modele}) {periode['debut']}-{periode['fin']} "
        f"pour ({site['latitude']}, {site['longitude']})…"
    )
    horaire = fetch_historique(
        latitude=site["latitude"],
        longitude=site["longitude"],
        annee_debut=periode["debut"],
        annee_fin=periode["fin"],
        modele=modele,
    )
    print(f"  {len(horaire):,} heures récupérées.")

    quot = agreger_quotidien(horaire, site["latitude"], site["longitude"], site["altitude"])

    # Jour de l'année (1-366) pour le groupby.
    quot["doy"] = pd.to_datetime(quot.index).dayofyear
    normale = quot.groupby("doy")[["t_min_celsius", "t_max_celsius", "t_moy_celsius"]].mean()
    normale.index.name = "day_of_year"

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    normale.round(2).to_csv(OUTPUT_CSV)
    print(f"Normale écrite : {OUTPUT_CSV.relative_to(REPO_ROOT)} ({len(normale)} jours)")


if __name__ == "__main__":
    main()
