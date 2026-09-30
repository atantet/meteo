#!/usr/bin/env python
"""Entraîne et sérialise le Random Forest de nébulosité (ADR à rédiger).

Contexte
--------
Le moteur à seuils (``_SEUILS_NEBULOSITE_PCT``) plafonne à une MAE de 0,514
en validation temporelle (train juin-août / test septembre) quels que soient
les seuils — cf. ``docs/calibration_pictos.md``, entrée 2026-09-30. Un Random
Forest à 7 features (cc, cc_low, cc_mid, precip, temp, visibilité, humidité)
réduit cette erreur à 0,392 (-24 %) sur le même test. Décision actée avec
Alexis : la performance mesurée guide le choix du moteur ; le principe
« pas de boîte noire » du projet porte sur la **transparence de la
méthodologie** (ce script, la donnée, la validation sont публics et
reproductibles), pas sur l'interdiction d'un type de modèle.

Usage
-----
    python calibration/train_nebulosite_rf.py

Produit ``src/meteo_socle/indices/data/nebulosite_rf.joblib``, chargé au vol
par ``meteo_socle.indices.temps_sensible.nebulosite_rf``. Entraîné sur la
**totalité** des tranches ciel disponibles (source ``hora_diag``, features
complètes) — validé séparément en temporel avant ce refit final (voir
``docs/calibration_pictos.md``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

REPO_ROOT = Path(__file__).resolve().parents[1]
_DATASET = REPO_ROOT / "data" / "calibration" / "dataset.csv"
_MODELE_SORTIE = REPO_ROOT / "src" / "meteo_socle" / "indices" / "data" / "nebulosite_rf.joblib"

#: Ordre des features — DOIT être identique à l'inférence
#: (``temps_sensible.nebulosite_rf``) et à ``calibration/optimize.py``.
FEATURES = [
    "cc_avg",
    "cc_low_avg",
    "cc_mid_avg",
    "precip_sum",
    "temp_c_avg",
    "visi_m_min",
    "humi_avg",
]


def charger_donnees_completes(dataset_csv: Path) -> pd.DataFrame:
    """Tranches ciel (MF non pluvieux) aux 7 features complètes (source hora_diag)."""
    df = pd.read_csv(dataset_csv)
    df_sky = df[df["mf_wmo"].isin([0, 1, 2, 3])].copy()
    return df_sky.dropna(subset=FEATURES)


def entrainer(df_complet: pd.DataFrame) -> RandomForestClassifier:
    x = df_complet[FEATURES].to_numpy()
    y = df_complet["mf_wmo"].to_numpy()
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=4,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=42,
    )
    rf.fit(x, y)
    return rf


def main() -> None:
    df_complet = charger_donnees_completes(_DATASET)
    print(f"Entraînement sur {len(df_complet)} tranches (7 features complètes).")
    if len(df_complet) < 30:
        print("Dataset trop petit — abandon (pas de modèle produit).", file=sys.stderr)
        sys.exit(1)

    rf = entrainer(df_complet)
    pred = rf.predict(df_complet[FEATURES].to_numpy())
    mae_train = float(np.mean(np.abs(pred - df_complet["mf_wmo"].to_numpy())))
    print(f"MAE en ré-application sur le train (indicatif, pas une validation) : {mae_train:.3f}")
    print("Rappel validation temporelle (train juin-août / test septembre) : 0,392")
    print("(cf. docs/calibration_pictos.md, entrée 2026-09-30)")

    _MODELE_SORTIE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(rf, _MODELE_SORTIE)
    print(f"Modèle écrit → {_MODELE_SORTIE}")


if __name__ == "__main__":
    main()
