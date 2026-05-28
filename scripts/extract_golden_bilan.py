"""Phase A — génération du golden test pour `bilan.py`
(bilan hydrique culture-spécifique avec coefficients culturaux ARDEPI).

Importe `bilan.calcul_bilan` depuis `app-bilan-hydrique` et l'exécute
sur un scénario type :

- 3 jours consécutifs de météo (ETP horaire agrégée en quotidien sur
  la base du golden ETP du 15 juin 2024 à La Petite Claye) ;
- Tomate, stade *De la floraison du 3ème bouquet à la mi-récolte* (Kc = 0.9) ;
- Sol *Terres limono-sablo-argileuses*, fraction cailloux 0.05 ;
- RU initialement remplie à 80 %, RFU = 60 % de la RU ;
- Seuil d'irrigation à 5 mm, conversion hauteur→durée 2 h/mm.

Sauve `(input, output)` en CSV sous `tests/golden/data/`.

USAGE
=====

    ~/.conda/envs/app_bilan_hydrique/bin/python scripts/extract_golden_bilan.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = Path.home() / "Documents/Travail/1_agri/Technique/app-bilan-hydrique"

# bilan.py charge `coefficients_culturaux_ardepi.json` via une path relative
# au cwd — on chdir avant import.
os.chdir(SRC_DIR)
sys.path.insert(0, str(SRC_DIR))

import bilan  # noqa: E402

# Scénario type : 3 jours de juin avec ETP montant et une journée de pluie.
df_input = pd.DataFrame(
    {
        "etp": [3.5, 4.0, 4.2],
        "precipitation": [0.0, 0.0, 6.0],
    },
    index=pd.to_datetime(["2024-06-15", "2024-06-16", "2024-06-17"], utc=True),
)

PARAMS = dict(
    texture="Terres limono-sablo-argileuses",
    fraction_cailloux=0.05,
    culture="Tomate",
    stade="De la floraison du 3ème bouquet à la mi-récolte",
    fraction_ru_remplie=0.8,
    ru_vers_rfu=0.6,
    seuil_irrigation=5.0,
    hauteur_vers_duree_irrigation=2.0,
)

GOLDEN_DIR = REPO_ROOT / "tests/golden/data"
INPUT_GOLDEN = GOLDEN_DIR / "bilan_input.csv"
PARAMS_GOLDEN = GOLDEN_DIR / "bilan_params.csv"
OUTPUT_GOLDEN = GOLDEN_DIR / "bilan_output.csv"


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    df_input.to_csv(INPUT_GOLDEN)
    pd.Series(PARAMS, name="value").to_csv(PARAMS_GOLDEN, header=True)

    result = bilan.calcul_bilan(df_input, **PARAMS)
    result.to_csv(OUTPUT_GOLDEN, float_format="%.10g")

    print(f"Input   : {INPUT_GOLDEN.relative_to(REPO_ROOT)}")
    print(f"Params  : {PARAMS_GOLDEN.relative_to(REPO_ROOT)}")
    print(f"Output  : {OUTPUT_GOLDEN.relative_to(REPO_ROOT)}")
    print()
    print(result.round(3).to_string())


if __name__ == "__main__":
    main()
