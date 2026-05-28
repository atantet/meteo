"""Golden test bilan hydrique culture-spécifique — characterization Phase A.

Vérifie que `meteo_socle.indices.bilan_hydrique.calcul_bilan` reproduit
fidèlement le comportement de `app-bilan-hydrique/bilan.py` sur un
scénario type Tomate / sol limono-sablo-argileux / 3 jours de juin
2024 (cf. ADR-0003).

Le golden CSV a été généré par `scripts/extract_golden_bilan.py`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

GOLDEN_DIR = Path(__file__).parent / "data"
INPUT_CSV = GOLDEN_DIR / "bilan_input.csv"
PARAMS_CSV = GOLDEN_DIR / "bilan_params.csv"
OUTPUT_CSV = GOLDEN_DIR / "bilan_output.csv"


@pytest.fixture(scope="module")
def bilan_input() -> pd.DataFrame:
    return pd.read_csv(INPUT_CSV, index_col=0, parse_dates=True)


@pytest.fixture(scope="module")
def bilan_params() -> dict:
    df = pd.read_csv(PARAMS_CSV, index_col=0)
    raw = df["value"].to_dict()
    typed = {}
    for k, v in raw.items():
        if k in (
            "fraction_cailloux",
            "fraction_ru_remplie",
            "ru_vers_rfu",
            "seuil_irrigation",
            "hauteur_vers_duree_irrigation",
        ):
            typed[k] = float(v)
        else:
            typed[k] = v
    return typed


@pytest.fixture(scope="module")
def bilan_expected() -> pd.DataFrame:
    return pd.read_csv(OUTPUT_CSV, index_col=0, parse_dates=True)


@pytest.mark.golden
def test_calcul_bilan_golden(
    bilan_input: pd.DataFrame,
    bilan_params: dict,
    bilan_expected: pd.DataFrame,
) -> None:
    """Bilan hydrique Tomate sur 3 jours juin 2024 — comportement figé."""
    try:
        from meteo_socle.indices.bilan_hydrique import calcul_bilan
    except ImportError:
        pytest.skip(
            "meteo_socle.indices.bilan_hydrique non encore implémenté "
            "(Phase B à venir, cf. ADR-0003)"
        )

    result = calcul_bilan(bilan_input, **bilan_params)

    pd.testing.assert_frame_equal(
        result,
        bilan_expected,
        check_dtype=False,
        rtol=1e-6,
        atol=1e-9,
    )
