"""Phase A — génération du golden test ETP FAO Penman-Monteith horaire.

Importe `etp.calcul_etp` depuis le dépôt antérieur `app-bilan-hydrique`
(cf. ADR-0003 characterization testing) et l'applique à 24 h
d'observations horaires interpolées DPClim multi-stations au site de
référence La Petite Claye des Champs (8 La Petite Claye, 35610
Pleine-Fougères — cf. ADR-0001 règle 3), en respectant les conventions
d'unités `meteofrance.VARIABLES_CONVERSION_UNITES['DPClim']`.

Sauve (input horaire converti en unités SI, output ETP horaire) en CSV
sous `tests/golden/data/` pour servir de **golden de migration**.

USAGE
=====

Une seule exécution suffit (le golden est ensuite versionné dans le
repo) :

    ~/.conda/envs/app_bilan_hydrique/bin/python scripts/extract_golden_etp.py

Idempotent : ré-exécution → même fichier produit (modulo timestamp de
fichier).

NOTES
=====

- Le script ne modifie ni ne déplace aucun fichier de
  `app-bilan-hydrique` — il importe uniquement ses modules.
- La fenêtre 24 h en juin 2024 couvre lever/coucher solaire, nébulosité
  variable et pluie légère — couvre tous les chemins du code dans
  `calcul_etp` (y compris la propagation nuit-jour du clearness ratio).
- Le centroïde commune Pleine-Fougères est utilisé comme site de
  référence (cf. discipline géoloc grain commune, ADR-0001).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = Path.home() / "Documents/Travail/1_agri/Technique/app-bilan-hydrique"

# Le code à caractériser est dans SRC_DIR. On l'ajoute au PYTHONPATH sans
# le copier dans notre repo (la copie verbatim sera faite en Phase B,
# cf. ADR-0003).
sys.path.insert(0, str(SRC_DIR))

import etp  # noqa: E402  (import après modification de sys.path)

# Site de référence : 8 La Petite Claye, 35610 Pleine-Fougères
# (géocodage Nominatim OSM). Inscrit en clair cf. ADR-0001 règle 3.
SITE_LAT = 48.5420
SITE_LON = -1.6155
SITE_ALT = 30.0

# Fenêtre d'entrée : 24 h en été (15 juin 2024).
_INPUT_FNAME = "donnees_DPClim_horaire_lapetiteclaye_nn9_20240101T000000Z_20241231T235959Z_ref.csv"
INPUT_CSV = SRC_DIR / "data/DPClim" / _INPUT_FNAME
START = "2024-06-15 00:00:00+00:00"
END = "2024-06-15 23:00:00+00:00"

OUTPUT_CSV = REPO_ROOT / "tests/golden/data/etp_fao_24h_lapetiteclaye_2024-06-15.csv"


def main() -> None:
    df_raw = pd.read_csv(INPUT_CSV, index_col=0, parse_dates=True)
    df_window = df_raw.loc[START:END].copy()
    assert len(df_window) == 24, f"Attendu 24 heures, trouvé {len(df_window)}"

    # Conversions d'unités cf. `meteofrance.VARIABLES_CONVERSION_UNITES['DPClim']`.
    df_input = pd.DataFrame(index=df_window.index)
    df_input["temperature_2m"] = df_window["T"] + 273.15  # °C → K
    df_input["humidite_relative"] = df_window["U"] / 100.0  # % → fraction
    df_input["vitesse_vent_10m"] = df_window["FF"]  # m/s
    df_input["rayonnement_global"] = df_window["GLO"] * 1.0e4  # J/cm²/h → J/m²/h
    df_input["precipitation"] = df_window["RR1"]  # mm

    etp_h = etp.calcul_etp(df_input, SITE_LAT, SITE_LON, SITE_ALT)

    golden = df_input.copy()
    golden["etp_ref"] = etp_h

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    # CSV plutôt que parquet : 24 lignes, lisible humain, pas de dépendance
    # pyarrow/fastparquet pour générer le golden.
    golden.to_csv(OUTPUT_CSV, float_format="%.10g")

    print(f"Golden écrit : {OUTPUT_CSV.relative_to(REPO_ROOT)}")
    print(
        f"  {len(golden)} lignes, "
        f"ETP horaires (mm/h) : min={golden['etp_ref'].min():.4f} "
        f"max={golden['etp_ref'].max():.4f}, "
        f"total 24h = {golden['etp_ref'].sum():.4f} mm"
    )


if __name__ == "__main__":
    main()
