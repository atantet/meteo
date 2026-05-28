"""Golden test ETP FAO Penman-Monteith — characterization testing Phase A.

Vérifie que `meteo_socle.indices.etp_fao.calcul_etp` reproduit fidèlement
le comportement de l'implémentation antérieure (`app-bilan-hydrique/etp.py`)
sur 24 h d'observations DPClim juin 2024 à Pleine-Fougères (cf. ADR-0003).

Le golden CSV a été généré par `scripts/extract_golden_etp.py`. Toute
modification de `calcul_etp` doit conserver ce test vert (sauf
modification scientifique délibérée actée en ADR de remédiation).

Tolérance : rtol=1e-6 atol=1e-9 — précision machine pour les valeurs
typiques d'ETP horaire en mm/h (~1e-2 à 1e-1).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

GOLDEN_CSV = Path(__file__).parent / "data" / "etp_fao_24h_lapetiteclaye_2024-06-15.csv"

# Site de référence cf. ADR-0001 règle 3 (mêmes coords que le script de
# génération du golden).
SITE_LAT = 48.5420
SITE_LON = -1.6155
SITE_ALT = 30.0

INPUT_COLUMNS = [
    "temperature_2m",
    "humidite_relative",
    "vitesse_vent_10m",
    "rayonnement_global",
    "precipitation",
]


@pytest.fixture(scope="module")
def golden_data() -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_csv(GOLDEN_CSV, index_col=0, parse_dates=True)
    return df[INPUT_COLUMNS].copy(), df["etp_ref"].copy()


@pytest.mark.golden
def test_calcul_etp_golden_2024_06_15(
    golden_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    """ETP horaire FAO P-M sur 24 h juin 2024 — comportement figé Phase A."""
    try:
        from meteo_socle.indices.etp_fao import calcul_etp
    except ImportError:
        pytest.skip(
            "meteo_socle.indices.etp_fao non encore implémenté "
            "(Phase B à venir, cf. ADR-0003)"
        )

    input_df, expected = golden_data
    result = calcul_etp(input_df, SITE_LAT, SITE_LON, SITE_ALT)

    actual = pd.Series(result.values, index=result.index, name="etp_ref")
    pd.testing.assert_series_equal(
        actual,
        expected,
        check_dtype=False,
        rtol=1e-6,
        atol=1e-9,
    )
