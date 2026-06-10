"""Calcul du bilan hydrique de l'atelier — pur (sans Streamlit).

Partagé entre l'app Streamlit (``streamlit_app.py``) et le script de preview
(``scripts/preview_veille_atelier.py``) pour garantir que le bilan affiché par
Streamlit et celui qu'on prévisualise hors-ligne reposent **exactement** sur la
même prévision (run ARPEGE 00Z du jour) et les **mêmes paramètres par défaut**
— donc « reliés », sans dérive possible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from apps.operationnelle.charts import bilan_culture_carry_over, bilan_tunnel_carry_over
from apps.operationnelle.indicateurs import (
    calculer_indicateurs_quotidiens,
    jours_complets_seulement,
)
from meteo_socle.sources.openmeteo_runs import (
    ARPEGE,
    VARS_MONO_MODELE,
    OpenMeteoSingleRuns,
)

_SRC = Path(__file__).resolve().parents[2] / "src"
KC_JSON_PATH = _SRC / "meteo_socle" / "indices" / "coefficients_culturaux_ardepi.json"

# Paramètres par défaut de l'atelier (= valeurs initiales des sliders). Le script
# de preview les réutilise tels quels → la vue par défaut de Streamlit et le
# preview hors-ligne sont identiques.
PARAMS_DEFAUT: dict[str, float | str] = {
    "culture": "Tomate",
    "texture": "Terres limono-argileuses",
    "fraction_cailloux": 0.05,
    "ru_vers_rfu": 0.60,
    "fraction_ru_remplie_initial": 1.00,
    "apport_max_mm": 25.0,
    "k_tunnel": 0.70,
}


def charger_coefficients() -> dict[str, dict[str, float]]:
    """Coefficients culturaux ARDEPI (Kc par culture × stade)."""
    with open(KC_JSON_PATH) as f:
        return json.load(f)


def stade_defaut(coefficients: dict[str, dict[str, float]], culture: str) -> str:
    """Premier stade phénologique de la culture (défaut des sélecteurs)."""
    return next(iter(coefficients[culture]))


def run_00z(now_utc: pd.Timestamp) -> pd.Timestamp:
    """Run ARPEGE de référence = 00Z du jour (bilan depuis J+0 00Z)."""
    return now_utc.normalize()


def fetch_arpege_run(
    latitude: float,
    longitude: float,
    horizon_jours: int,
    run_utc: pd.Timestamp,
    source: OpenMeteoSingleRuns | None = None,
) -> pd.DataFrame:
    """Récupère un run ARPEGE précis (args primitifs → cacheable côté Streamlit)."""
    src = source or OpenMeteoSingleRuns()
    df = src.obtenir_run(ARPEGE, run_utc, latitude, longitude, horizon_jours, VARS_MONO_MODELE)
    if df is None or df.empty:
        raise RuntimeError(f"Run ARPEGE {run_utc} muet.")
    return df


def quotidien_du_jour(config: dict, prevision: pd.DataFrame, now_utc: pd.Timestamp) -> pd.DataFrame:
    """Indicateurs quotidiens depuis J+0 00Z, jours complets uniquement (4 j)."""
    quotidien = calculer_indicateurs_quotidiens(prevision, config, now_utc=now_utc.normalize())
    return jours_complets_seulement(quotidien, prevision)


def bilans(
    quotidien: pd.DataFrame,
    *,
    culture: str,
    stade: str,
    texture: str,
    fraction_cailloux: float,
    ru_vers_rfu: float,
    fraction_ru_remplie_initial: float,
    apport_max_mm: float,
    k_tunnel: float,
    seuil_irrigation_mm: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bilans plein champ + sous abri (FAO 56). Renvoie ``(bilan_pa, bilan_tu)``."""
    params = dict(
        texture=texture,
        fraction_cailloux=fraction_cailloux,
        culture=culture,
        stade=stade,
        fraction_ru_remplie_initial=fraction_ru_remplie_initial,
        ru_vers_rfu=ru_vers_rfu,
        seuil_irrigation_mm=seuil_irrigation_mm,
        apport_max_mm=apport_max_mm,
    )
    bilan_pa = bilan_culture_carry_over(quotidien, k_etp_ratio=1.0, inclure_pluie=True, **params)
    bilan_tu = bilan_tunnel_carry_over(quotidien, k_tunnel=k_tunnel, **params)
    return bilan_pa, bilan_tu
