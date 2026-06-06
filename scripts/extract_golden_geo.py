"""Phase A — génération du golden test pour `geo.py` (sélection N stations
les plus proches + interpolation inverse-distance²).

Importe `geo.selection_stations_plus_proches` et
`geo.interpolation_inverse_distance_carre` depuis `app-bilan-hydrique`
et les exécute sur :

- une liste synthétique de 5 stations autour de Pleine-Fougères
  (centroïde commune 48.50 N, 1.55 W) ;
- une série de valeurs météo aux 3 stations sélectionnées comme plus
  proches, à interpoler vers le site de référence.

Sauve `(input synthétique, output)` en CSV sous `tests/golden/data/`.

USAGE
=====

    ~/.conda/envs/app_bilan_hydrique/bin/python scripts/extract_golden_geo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = Path.home() / "Documents/Travail/1_agri/Technique/app-bilan-hydrique"
sys.path.insert(0, str(SRC_DIR))

import geo  # noqa: E402

# Site de référence : 8 La Petite Claye, 35610 Pleine-Fougères
# (géocodage BAN). Cf. ADR-0001 règle 3.
SITE_LAT = 48.543648
SITE_LON = -1.611515

# 5 stations synthétiques. Coordonnées et altitudes vaguement
# représentatives de la zone Bretagne-nord / Manche-ouest. Distance à
# Pleine-Fougères : entre ~10 km et ~50 km.
STATIONS = pd.DataFrame(
    {
        "Id_station": ["S1", "S2", "S3", "S4", "S5"],
        "Nom": ["NORD_PROCHE", "EST_PROCHE", "SUD_PROCHE", "OUEST_LOIN", "NORD_LOIN"],
        "Latitude": [48.58, 48.50, 48.40, 48.50, 48.85],
        "Longitude": [-1.55, -1.40, -1.55, -2.05, -1.60],
        "Altitude": [50, 70, 90, 60, 30],
    }
).set_index("Id_station")

LATLON_LABELS = ["Latitude", "Longitude"]

GOLDEN_DIR = REPO_ROOT / "tests/golden/data"
STATIONS_GOLDEN = GOLDEN_DIR / "geo_stations_input.csv"
NEAREST_GOLDEN = GOLDEN_DIR / "geo_nearest_3.csv"
INTERPOLATED_GOLDEN = GOLDEN_DIR / "geo_interpolated_idw2.csv"


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    # Sauvegarder l'input synthétique pour le test.
    STATIONS.to_csv(STATIONS_GOLDEN)

    # Sélection des 3 plus proches.
    ref_latlon = np.array([SITE_LAT, SITE_LON])
    nearest = geo.selection_stations_plus_proches(STATIONS, ref_latlon, LATLON_LABELS, nombre=3)
    nearest.to_csv(NEAREST_GOLDEN)

    # Interpolation inverse-distance² d'une série météo synthétique.
    # Trois variables × deux pas de temps × trois stations.
    times = pd.to_datetime(["2024-06-15 06:00:00+00:00", "2024-06-15 12:00:00+00:00"], utc=True)
    multiindex = pd.MultiIndex.from_product([nearest.index, times], names=["station", "time"])
    np.random.seed(0)  # déterminisme du golden
    values = pd.DataFrame(
        np.random.uniform(low=[10, 60, 2], high=[20, 90, 8], size=(6, 3)),
        index=multiindex,
        columns=["temperature_2m", "humidite_relative", "vitesse_vent_10m"],
    )
    interpolated = geo.interpolation_inverse_distance_carre(values, nearest["distance"])
    interpolated.to_csv(INTERPOLATED_GOLDEN)

    print(f"Stations input  : {STATIONS_GOLDEN.relative_to(REPO_ROOT)}")
    print(f"Nearest 3       : {NEAREST_GOLDEN.relative_to(REPO_ROOT)}")
    print(f"  IDs={list(nearest.index)} distances={list(nearest['distance'].astype(int))} km")
    print(f"Interpolated    : {INTERPOLATED_GOLDEN.relative_to(REPO_ROOT)}")
    print("  valeurs interpolées au site de référence :")
    for col in interpolated.columns:
        for t, v in interpolated[col].items():
            print(f"    {col} @ {t} = {v:.4f}")


if __name__ == "__main__":
    main()
