"""Pré-calcul de la normale climatologique journalière pour le site Veille.

Récupère la **normale OMM standard 1991-2020 (30 ans)** d'ERA5 via
Open-Meteo Archive, agrège en quotidien (T_min, T_max, T_moy), puis
moyenne par jour-de-l'année → 366 valeurs.

Sauve le CSV de référence ``data/climato/normale_jour_lapetiteclaye.csv``
versionné dans le repo et utilisé en overlay par
``apps.veille.charts.graphique_72h_base64``.

Les bornes sont lues dans ``config/climato.yaml`` :
``periodes.normale_debut`` / ``periodes.normale_fin``.

USAGE
=====

À exécuter ponctuellement (rare — pas dans le cron Veille) :

    ~/.conda/envs/meteo/bin/python scripts/compute_normale_jour.py

Coût : ~3-5 min pour 30 ans (1 requête Open-Meteo par an).
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
from apps.climato.donnees import charger_historique_cache, fetch_historique  # noqa: E402

OUTPUT_CSV = REPO_ROOT / "data" / "climato" / "normale_jour_lapetiteclaye.csv"


def main() -> None:
    config = load_config()
    site = config["site"]
    # Normale OMM standard (30 ans) — pas la fenêtre démo du rapport.
    debut = config["periodes"]["normale_debut"]
    fin = config["periodes"]["normale_fin"]
    modele = config["source_meteo"]["modele"]

    # Préférer le cache parquet s'il couvre la fenêtre demandée — évite
    # 30 appels HTTP successifs (~3-5 min).
    horaire = None
    try:
        horaire = charger_historique_cache(annee_debut=debut, annee_fin=fin)
        print(f"Cache parquet lu : {len(horaire):,} heures pour {debut}-{fin}.")
    except (FileNotFoundError, ValueError, KeyError):
        print(
            f"Fetch archive ({modele}) {debut}-{fin} "
            f"(normale OMM, {fin - debut + 1} ans) "
            f"pour ({site['latitude']}, {site['longitude']})…"
        )
        horaire = fetch_historique(
            latitude=site["latitude"],
            longitude=site["longitude"],
            annee_debut=debut,
            annee_fin=fin,
            modele=modele,
        )
        print(f"  {len(horaire):,} heures récupérées.")

    quot = agreger_quotidien(horaire, site["latitude"], site["longitude"], site["altitude"])

    # Jour de l'année (1-366) pour le groupby.
    quot["doy"] = pd.to_datetime(quot.index).dayofyear
    normale = quot.groupby("doy")[["t_min_celsius", "t_max_celsius", "t_moy_celsius"]].mean()

    # Ajout normale HR moyenne (%) par jour de l'année, calculée
    # directement depuis le DataFrame horaire (la HR n'est pas dans
    # ``agreger_quotidien`` standard — sortie spécifique Veille).
    horaire_hr = horaire.copy()
    horaire_hr["doy"] = pd.DatetimeIndex(horaire_hr.index).dayofyear
    normale["hr_moy_pct"] = horaire_hr.groupby("doy")["humidite_relative"].mean() * 100.0

    normale.index.name = "day_of_year"

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    normale.round(2).to_csv(OUTPUT_CSV)
    print(f"Normale écrite : {OUTPUT_CSV.relative_to(REPO_ROOT)} ({len(normale)} jours)")


if __name__ == "__main__":
    main()
