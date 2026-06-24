#!/usr/bin/env python
"""Optimise les seuils de pictogramme et entraîne RF + DT sur le dataset labelisé.

Usage
-----
    python calibration/optimize.py
    python calibration/optimize.py --dataset data/calibration/dataset.csv

Deux approches complémentaires
-------------------------------
(A) **Differential Evolution** (scipy) — optimise le vecteur de seuils
    ``(s1, s2, s3, s_circ)`` en minimisant l'erreur ordinale sur les tranches
    du dataset. Reste dans la structure de règle actuelle → résultat directement
    reportable dans ``temps_sensible.py``.

(B) **Random Forest** (sklearn, n=200) + **Decision Tree** (max_depth=3) —
    apprennent librement depuis les features AROME agrégées (cc_avg, cc_low_avg,
    cc_mid_avg, precip_sum …). RF = modèle principal ; DT = proxy lisible pour
    valider que les splits ont un sens physique. Feature importances RF révèlent
    si la structure de règle actuelle est sous-optimale.

Filtres appliqués
-----------------
- Orage (mf_wmo = 95) exclu : l'orage vient de la Vigilance, pas du moteur picto.
- Tranches sans features (cc_avg NaN) exclues.
- Pour DE : seules les tranches avec ``cc_hours`` disponibles (HORA-DIAG) sont
  utilisées pour le replay heure/heure ; les tranches PICTO-DIAG sont utilisées
  en features agrégées.

Seuils actuels (référence)
---------------------------
    s1=13, s2=38, s3=86   (_SEUILS_NEBULOSITE_PCT dans temps_sensible.py)
    s_circ=13             (seuil bas+moy pour la réduction cirrus)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import differential_evolution
from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier, export_text

_DATASET_DEFAULT = Path("data/calibration/dataset.csv")

# Seuils actuels → référence et point de départ pour DE
_S1_CUR, _S2_CUR, _S3_CUR, _S_CIRC_CUR = 13.0, 38.0, 86.0, 13.0


# ---------------------------------------------------------------------------
# Règle paramétrisée (rejoue temps_sensible.symbole_metno sans importer le module)
# ---------------------------------------------------------------------------


def _nebulosite(cc_pct: float, s1: float, s2: float, s3: float) -> int:
    if cc_pct <= s1:
        return 0
    if cc_pct <= s2:
        return 1
    if cc_pct <= s3:
        return 2
    return 3


def _code_heure(
    cc: float | None,
    cc_low: float | None,
    cc_mid: float | None,
    precip: float | None,
    s1: float,
    s2: float,
    s3: float,
    s_circ: float,
) -> int | None:
    """Code OMM (0-3) pour une heure avec les seuils paramétrés."""
    if cc is None:
        return None
    neb = _nebulosite(cc, s1, s2, s3)
    gouttes = (precip or 0.0) >= 0.1
    cirrus_seul = (
        not gouttes
        and cc_low is not None
        and cc_mid is not None
        and neb >= 1
        and _nebulosite(cc_low, s1, s2, s3) == 0
        and _nebulosite(cc_mid, s1, s2, s3) == 0
    )
    if cirrus_seul:
        neb = 0
    return neb


def _code_fenetre(codes: list[int | None]) -> int | None:
    """Agrégation 6 h (reproduit code_dominant_fenetre pour WMO 0-3 uniquement)."""
    valides = [c for c in codes if c is not None]
    if not valides:
        return None
    niveaux = np.array(valides)
    rep = int(niveaux.mean() + 0.5)
    if rep >= 3 and int(niveaux.min()) <= 2:
        rep = 2
    return rep


def _predict_tranche(row: pd.Series, s1: float, s2: float, s3: float, s_circ: float) -> int | None:
    """Code prédit pour une tranche avec les seuils donnés."""
    cc_h = _load_json(row.get("cc_hours"))
    cl_h = _load_json(row.get("cc_low_hours"))
    cm_h = _load_json(row.get("cc_mid_hours"))
    pr_h = _load_json(row.get("precip_hours"))

    if cc_h is not None:
        # Replay heure/heure (HORA-DIAG disponible)
        codes = [
            _code_heure(
                cc_h[i],
                cl_h[i] if cl_h else None,
                cm_h[i] if cm_h else None,
                pr_h[i] if pr_h else None,
                s1,
                s2,
                s3,
                s_circ,
            )
            for i in range(len(cc_h))
        ]
        return _code_fenetre(codes)
    # Fallback : feature agrégée (PICTO-DIAG)
    cc_avg = row.get("cc_avg")
    if cc_avg is None or np.isnan(cc_avg):
        return None
    return _code_heure(
        cc_avg,
        row.get("cc_low_avg"),
        row.get("cc_mid_avg"),
        0.0,
        s1,
        s2,
        s3,
        s_circ,
    )


def _load_json(val) -> list | None:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return None
    return None


# ---------------------------------------------------------------------------
# (A) Differential Evolution
# ---------------------------------------------------------------------------


def _objective(theta: np.ndarray, df_sky: pd.DataFrame) -> float:
    s1, s2, s3, s_circ = theta
    errs = []
    for _, row in df_sky.iterrows():
        pred = _predict_tranche(row, s1, s2, s3, s_circ)
        if pred is None:
            continue
        errs.append(abs(pred - int(row["mf_wmo"])))
    return float(np.mean(errs)) if errs else 1.0


def run_de(df_sky: pd.DataFrame) -> dict:
    bounds = [
        (1.0, 25.0),  # s1
        (20.0, 55.0),  # s2
        (60.0, 95.0),  # s3
        (1.0, 25.0),  # s_circ
    ]
    result = differential_evolution(
        _objective,
        bounds,
        args=(df_sky,),
        seed=42,
        maxiter=500,
        tol=1e-4,
        constraints=[],  # s1 < s2 < s3 géré par les bounds chevauchantes
        polish=True,
        disp=False,
    )
    s1, s2, s3, s_circ = result.x
    # Vérifier l'ordre (DE peut violer s1<s2<s3 avec des bounds larges)
    s1, s2, s3 = sorted([s1, s2, s3])
    return {
        "s1": round(s1, 1),
        "s2": round(s2, 1),
        "s3": round(s3, 1),
        "s_circ": round(s_circ, 1),
        "mae": round(result.fun, 3),
        "n": sum(
            1
            for _, row in df_sky.iterrows()
            if _predict_tranche(row, s1, s2, s3, s_circ) is not None
        ),
    }


# ---------------------------------------------------------------------------
# (B) Random Forest + Decision Tree
# ---------------------------------------------------------------------------

_FEATURES = ["cc_avg", "cc_low_avg", "cc_mid_avg", "precip_sum"]
_FEATURES_EXTRA = ["temp_c_avg", "visi_m_min", "humi_avg"]


def _build_xy(df_sky: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, list[str]]:
    feats = _FEATURES + [f for f in _FEATURES_EXTRA if df_sky[f].notna().any()]
    sub = df_sky[feats + ["mf_wmo"]].dropna(subset=["cc_avg"])
    # Impute NaN (winter features absent en été) par la médiane
    x_arr = sub[feats].fillna(sub[feats].median()).to_numpy()
    y_arr = sub["mf_wmo"].to_numpy()
    return x_arr, y_arr, feats


def run_forest(df_sky: pd.DataFrame) -> dict:
    x_arr, y_arr, feats = _build_xy(df_sky)
    if len(x_arr) < 5:
        return {"error": f"Dataset trop petit ({len(x_arr)} lignes) pour RF"}

    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=4,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=42,
        oob_score=True,
    )
    rf.fit(x_arr, y_arr)

    dt = DecisionTreeClassifier(max_depth=3, random_state=42)
    dt.fit(x_arr, y_arr)

    importances = dict(zip(feats, rf.feature_importances_.round(3), strict=True))
    dt_text = export_text(dt, feature_names=feats)

    return {
        "oob_score": round(rf.oob_score_, 3),
        "n_train": len(x_arr),
        "feature_importances": importances,
        "dt_rules": dt_text,
        "classes": rf.classes_.tolist(),
    }


# ---------------------------------------------------------------------------
# Référence actuelle
# ---------------------------------------------------------------------------


def _mae_current(df_sky: pd.DataFrame) -> float:
    errs = []
    for _, row in df_sky.iterrows():
        pred = _predict_tranche(row, _S1_CUR, _S2_CUR, _S3_CUR, _S_CIRC_CUR)
        if pred is None:
            continue
        errs.append(abs(pred - int(row["mf_wmo"])))
    return round(float(np.mean(errs)), 3) if errs else float("nan")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(dataset_csv: Path) -> None:
    df = pd.read_csv(dataset_csv)
    print(f"Dataset : {len(df)} tranches labelisées")

    # Filtre ciel uniquement (orage et pluie exclus pour l'optimisation des seuils ciel)
    df_sky = df[df["mf_wmo"].isin([0, 1, 2, 3])].copy()
    print(f"Tranches ciel (mf_wmo ∈ {{0,1,2,3}}) : {len(df_sky)}")
    if df_sky.empty:
        print("Rien à optimiser.")
        return

    # Baseline actuelle
    mae_cur = _mae_current(df_sky)
    print(
        f"\n--- Seuils actuels (s1={_S1_CUR}, s2={_S2_CUR}, s3={_S3_CUR}, s_circ={_S_CIRC_CUR}) ---"
    )
    print(f"MAE ordinale : {mae_cur}")

    # (A) Differential Evolution
    print("\n--- (A) Differential Evolution ---")
    de = run_de(df_sky)
    print(f"s1={de['s1']}  s2={de['s2']}  s3={de['s3']}  s_circ={de['s_circ']}")
    print(f"MAE optimisée : {de['mae']}  (sur {de['n']} tranches)")
    gain = mae_cur - de["mae"]
    print(f"Gain vs actuel : {gain:+.3f}")

    if gain > 0.01:
        print("\n→ Seuils à reporter dans temps_sensible.py :")
        print(f"    _SEUILS_NEBULOSITE_PCT = ({de['s1']}, {de['s2']}, {de['s3']})")
        print(f"    # seuil cirrus (bas+moy) : {de['s_circ']} %")
    else:
        print("→ Gain marginal (< 0.01) — seuils actuels OK.")

    # (B) Random Forest + Decision Tree
    print("\n--- (B) Random Forest (n=200, max_depth=4) ---")
    rf_res = run_forest(df_sky)
    if "error" in rf_res:
        print(rf_res["error"])
    else:
        print(f"OOB score : {rf_res['oob_score']} (n_train={rf_res['n_train']})")
        print("Feature importances :")
        for feat, imp in sorted(rf_res["feature_importances"].items(), key=lambda x: -x[1]):
            bar = "█" * int(imp * 30)
            print(f"  {feat:<15} {imp:.3f}  {bar}")
        print("\n--- Decision Tree (max_depth=3, proxy lisible) ---")
        print(rf_res["dt_rules"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default=_DATASET_DEFAULT, type=Path)
    args = ap.parse_args()
    main(args.dataset)
