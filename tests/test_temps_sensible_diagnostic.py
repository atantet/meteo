"""Tests du picto piloté par les diagnostics MF (ADR-0021) : phase PTYPE,
brouillard visibilité, **jamais d'orage** (Vigilance)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from meteo_socle.indices.temps_sensible import (
    code_wmo_diagnostic,
    phase_depuis_ptype,
    serie_code_temps_mf,
)


@pytest.mark.parametrize(
    ("code", "phase"),
    [
        (0, "rain"),  # aucune précip
        (1, "rain"),
        (2, "rain"),  # orage → phase pluie (l'orage relève de la Vigilance)
        (11, "rain"),
        (3, "verglas"),
        (12, "verglas"),
        (5, "snow"),
        (9, "snow"),
        (6, "sleet"),
        (7, "sleet"),
        (float("nan"), "rain"),
    ],
)
def test_phase_depuis_ptype(code: float, phase: str) -> None:
    assert phase_depuis_ptype(code) == phase


def test_ciel_clair_sec() -> None:
    assert code_wmo_diagnostic(0.1, 0.0, 0.0) == 0  # clair


def test_pluie_continue_couvert() -> None:
    # Couvert + pluie modérée + PTYPE pluie → pluie continue (61/63/65).
    code = code_wmo_diagnostic(0.95, 3.0, 1.0)
    assert code in (61, 63, 65)


def test_neige() -> None:
    code = code_wmo_diagnostic(0.95, 2.0, 5.0)  # PTYPE = neige
    assert code in (71, 73, 75)


def test_verglas() -> None:
    assert code_wmo_diagnostic(0.95, 1.0, 3.0) == 66  # pluie verglaçante légère
    assert code_wmo_diagnostic(0.95, 4.0, 3.0) == 67  # forte


def test_brouillard_visibilite_basse_sec() -> None:
    assert code_wmo_diagnostic(1.0, 0.0, 0.0, visibilite_m=300.0) == 45
    # Visibilité basse MAIS pluie → pas brouillard (la pluie prime).
    assert code_wmo_diagnostic(0.95, 2.0, 1.0, visibilite_m=300.0) != 45


def test_jamais_orage() -> None:
    # Quelle que soit l'intensité / le code, jamais 95/96/99 (orage = Vigilance).
    for precip in (0.0, 5.0, 50.0):
        for code in (1, 2, 5, 8):
            assert code_wmo_diagnostic(0.9, precip, float(code)) not in (95, 96, 99)


def test_serie_mf() -> None:
    idx = pd.date_range("2026-06-15", periods=3, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "cloud_cover": [0.1, 0.95, np.nan],  # clair, couvert, manquant
            "precipitation": [0.0, 3.0, 1.0],
            "type_precip": [0.0, 1.0, 5.0],
            "visibilite_m": [20000.0, 8000.0, 5000.0],
        },
        index=idx,
    )
    s = serie_code_temps_mf(df)
    assert s.iloc[0] == 0  # clair sec
    assert s.iloc[1] in (61, 63, 65)  # pluie continue
    assert pd.isna(s.iloc[2])  # cloud_cover manquant → <NA>
    assert s.name == "weather_code"
