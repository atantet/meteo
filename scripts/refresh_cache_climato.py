"""Rafraîchit le cache parquet de l'historique horaire ERA5.

Fetch via Open-Meteo Archive l'intégralité de la fenêtre ``periodes``
de ``config/climato.yaml``, et écrit le résultat compressé en parquet
dans ``data/climato/historique_horaire.parquet``.

Usage :
    python scripts/refresh_cache_climato.py [--check]

- Sans option : fetch + écrit le parquet.
- Avec ``--check`` : compare au cache existant et exit 1 si la donnée
  a changé (utile en CI pour ne committer que si nécessaire).

Coût ~5-10 min (30 requêtes annuelles + backoff éventuel). À lancer
manuellement après changement de site ou de période OMM, et chaque
mois via le workflow ``.github/workflows/refresh-climato-cache.yml``
pour intégrer les dernières années si la fenêtre les inclut.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Bootstrap d'import : exécutable depuis n'importe quel cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pandas as pd  # noqa: E402

from apps.climato.config import load_config  # noqa: E402
from apps.climato.donnees import CACHE_PATH, fetch_historique  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Comparer au cache existant, exit 1 si différent (sans réécrire).",
    )
    args = parser.parse_args()

    config = load_config()
    site = config["site"]
    periode = config["rapport"]["periode_donnees"]
    modele = config["source_meteo"]["modele"]

    log.info(
        "Fetch archive %d-%d via Open-Meteo (modèle %s, lat=%.4f, lon=%.4f)",
        periode["debut"],
        periode["fin"],
        modele,
        site["latitude"],
        site["longitude"],
    )

    horaire = fetch_historique(
        latitude=site["latitude"],
        longitude=site["longitude"],
        annee_debut=periode["debut"],
        annee_fin=periode["fin"],
        modele=modele,
    )
    log.info("Données : %d heures, %d colonnes.", len(horaire), len(horaire.columns))

    chemin = REPO_ROOT / CACHE_PATH
    chemin.parent.mkdir(parents=True, exist_ok=True)

    if args.check:
        if not chemin.exists():
            log.info("Cache absent → différent par définition.")
            return 1
        ancien = pd.read_parquet(chemin)
        # Tolérance flottante : si les valeurs ne diffèrent pas plus
        # qu'epsilon, on considère identique. Le simple equals() est
        # trop strict sur les arrondis Open-Meteo.
        if ancien.shape == horaire.shape and ancien.index.equals(horaire.index):
            diffs = (ancien - horaire).abs().max().max()
            if diffs < 1e-3:
                log.info("Cache à jour (diff max %.2e).", diffs)
                return 0
        log.info("Cache obsolète.")
        return 1

    # Écriture compressée. snappy = standard parquet, bon ratio
    # vitesse/taille, supporté nativement par pandas/pyarrow.
    horaire.to_parquet(chemin, compression="snappy")
    taille_mo = chemin.stat().st_size / 1_048_576
    log.info("Écrit %s (%.1f MB).", chemin, taille_mo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
