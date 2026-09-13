"""Peuple le cache ERA5 CDS committé de la climatologie de référence.

Fetch (une fois) les années ``reference_debut_annee``..``reference_fin_annee``
de ``config/bulletin_eau_mensuel.yaml`` et les écrit dans ``pluie.cache_dir``
(committé dans le repo). Ces années sont fixes : ce script n'a besoin d'être
relancé qu'après un changement de fenêtre de référence (cf. issue #56 —
un cache volatile `actions/cache` s'évince entre deux runs mensuels, d'où le
passage à un cache committé pour ces années terminées).

Usage :
    python scripts/seed_cache_era5_bulletin_eau.py

Coût : 1-13 min par année manquante (file d'attente CDS), rien si déjà présent.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from apps.bulletin_eau_mensuel.config import load_config  # noqa: E402
from meteo_socle.sources.era5_cds import Era5Cds  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    config = load_config()
    site = config["site"]
    pcfg = config.get("pluie", {})
    an0 = int(pcfg.get("reference_debut_annee", 1991))
    an1 = int(pcfg.get("reference_fin_annee", 2020))
    cache_dir_cfg = pcfg.get("cache_dir")
    if not cache_dir_cfg:
        log.error("pluie.cache_dir absent de la config — rien à peupler.")
        return 1
    cache_dir = REPO_ROOT / cache_dir_cfg
    cache_dir.mkdir(parents=True, exist_ok=True)

    arch = Era5Cds(cache_dir=cache_dir)
    log.info("Fetch/peuplement %d-%d dans %s…", an0, an1, cache_dir)
    arch.obtenir_precip_quotidien(
        site["latitude"], site["longitude"], f"{an0}-01-01", f"{an1}-12-31"
    )
    n = len(list(cache_dir.glob("*.parquet")))
    log.info("Cache peuplé : %d fichiers parquet dans %s.", n, cache_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
