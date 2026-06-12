"""Tests unitaires des helpers purs d'ARPEGE direct MF (sans réseau).

Le fetch WCS lui-même (OAuth + GetCoverage + GRIB) nécessite réseau + token MF :
non testé en CI. On verrouille ici les parties déterministes — surtout les
conventions d'unités et la direction du vent, sources classiques de bugs.
"""

from __future__ import annotations

import pandas as pd
import pytest

from meteo_socle.sources.meteofrance_arpege import (
    _convertir,
    _coverage_run,
    _LimiteurDebit,
    _suffixe_accum,
    vent_vitesse_direction,
)


@pytest.mark.parametrize(
    ("u", "v", "dir_attendue"),
    [
        (0.0, -1.0, 0.0),  # souffle vers le sud → vient du nord
        (-1.0, 0.0, 90.0),  # vers l'ouest → vient de l'est
        (0.0, 1.0, 180.0),  # vers le nord → vient du sud
        (1.0, 0.0, 270.0),  # vers l'est → vient de l'ouest
    ],
)
def test_vent_direction_cardinaux(u: float, v: float, dir_attendue: float) -> None:
    vitesse, direction = vent_vitesse_direction(u, v)
    assert vitesse == pytest.approx(1.0)
    assert direction == pytest.approx(dir_attendue)


def test_vent_vectorise() -> None:
    u = pd.Series([3.0, 0.0])
    v = pd.Series([4.0, -2.0])
    vit, _ = vent_vitesse_direction(u, v)
    assert list(vit.round(2)) == [5.0, 2.0]


def test_convertir_unites() -> None:
    assert _convertir(88.0, "pct_frac") == pytest.approx(0.88)  # % → fraction
    assert _convertir(3600.0, "Wm2", fenetre_s=3600.0) == pytest.approx(1.0)  # J/m²/1h → W/m²
    assert _convertir(10800.0, "Wm2", fenetre_s=10800.0) == pytest.approx(1.0)  # J/m²/3h
    assert _convertir(288.15, "K") == pytest.approx(288.15)  # passthrough


def test_suffixe_accumulation() -> None:
    assert _suffixe_accum(3600.0) == "_PT1H"
    assert _suffixe_accum(10800.0) == "_PT3H"


def test_coverage_run_format() -> None:
    run = pd.Timestamp("2026-06-12 00:00", tz="UTC")
    assert _coverage_run(run) == "2026-06-12T00.00.00Z"


def test_limiteur_debit_laisse_passer_la_capacite() -> None:
    lim = _LimiteurDebit(max_par_minute=3)
    for _ in range(3):
        lim.acquerir()  # ne doit pas bloquer sous la capacité
    assert len(lim._instants) == 3
