"""Golden test geo — characterization testing Phase A.

Vérifie que `meteo_socle.geo.selection_stations_plus_proches` et
`meteo_socle.geo.interpolation_inverse_distance_carre` reproduisent
fidèlement le comportement de `app-bilan-hydrique/geo.py` (cf. ADR-0003).

Les golden CSV ont été générés par `scripts/extract_golden_geo.py`
(5 stations synthétiques + IDW² depuis 3 plus proches).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

GOLDEN_DIR = Path(__file__).parent / "data"
STATIONS_CSV = GOLDEN_DIR / "geo_stations_input.csv"
NEAREST_CSV = GOLDEN_DIR / "geo_nearest_3.csv"
INTERPOLATED_CSV = GOLDEN_DIR / "geo_interpolated_idw2.csv"

# Site de référence cf. ADR-0001 règle 3.
SITE_LAT = 48.543648
SITE_LON = -1.611515
LATLON_LABELS = ["Latitude", "Longitude"]
NB_NEAREST = 3


@pytest.fixture(scope="module")
def stations_input() -> pd.DataFrame:
    return pd.read_csv(STATIONS_CSV, index_col="Id_station")


@pytest.fixture(scope="module")
def expected_nearest() -> pd.DataFrame:
    return pd.read_csv(NEAREST_CSV, index_col="Id_station")


@pytest.fixture(scope="module")
def expected_interpolated() -> pd.DataFrame:
    return pd.read_csv(INTERPOLATED_CSV, index_col=0, parse_dates=True)


@pytest.mark.golden
def test_selection_stations_plus_proches_golden(
    stations_input: pd.DataFrame,
    expected_nearest: pd.DataFrame,
) -> None:
    """Sélection des 3 plus proches voisins parmi 5 stations synthétiques."""
    try:
        from meteo_socle.geo import selection_stations_plus_proches
    except ImportError:
        pytest.skip("meteo_socle.geo non encore implémenté (Phase B à venir)")

    ref_latlon = np.array([SITE_LAT, SITE_LON])
    nearest = selection_stations_plus_proches(
        stations_input, ref_latlon, LATLON_LABELS, nombre=NB_NEAREST
    )

    # Vérif identité des stations (ordre par distance compris).
    assert list(nearest.index) == list(expected_nearest.index)
    # Vérif distances entières (arrondies dans le code original).
    pd.testing.assert_series_equal(
        nearest["distance"].astype(int),
        expected_nearest["distance"].astype(int),
        check_names=False,
    )


@pytest.mark.golden
def test_interpolation_inverse_distance_carre_golden(
    stations_input: pd.DataFrame,
    expected_nearest: pd.DataFrame,
    expected_interpolated: pd.DataFrame,
) -> None:
    """Interpolation IDW² de variables météo synthétiques aux 3 plus proches."""
    try:
        from meteo_socle.geo import (
            interpolation_inverse_distance_carre,
            selection_stations_plus_proches,
        )
    except ImportError:
        pytest.skip("meteo_socle.geo non encore implémenté (Phase B à venir)")

    ref_latlon = np.array([SITE_LAT, SITE_LON])
    nearest = selection_stations_plus_proches(
        stations_input, ref_latlon, LATLON_LABELS, nombre=NB_NEAREST
    )

    # Reconstruction du même MultiIndex synthétique que dans le script.
    times = pd.to_datetime(["2024-06-15 06:00:00+00:00", "2024-06-15 12:00:00+00:00"], utc=True)
    multiindex = pd.MultiIndex.from_product([nearest.index, times], names=["station", "time"])
    np.random.seed(0)
    values = pd.DataFrame(
        np.random.uniform(low=[10, 60, 2], high=[20, 90, 8], size=(6, 3)),
        index=multiindex,
        columns=["temperature_2m", "humidite_relative", "vitesse_vent_10m"],
    )

    interpolated = interpolation_inverse_distance_carre(values, nearest["distance"])

    pd.testing.assert_frame_equal(
        interpolated.reset_index(drop=False).set_index(interpolated.index.name),
        expected_interpolated,
        check_dtype=False,
        rtol=1e-6,
        atol=1e-9,
    )
