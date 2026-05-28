"""Tests `apps.operationnelle.ui_helpers`."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


ALERTES_TEST = {
    "gel": {"actif": True, "seuil_celsius": -2.0},
    "canicule": {"actif": True, "seuil_celsius": 32.0},
    "pluie_intense": {"actif": True, "seuil_mm_24h": 20.0},
    "vent_fort": {"actif": True, "seuil_kmh": 60.0},
}


def _quotidien_synth() -> pd.DataFrame:
    dates = pd.to_datetime(["2024-06-15", "2024-06-16", "2024-06-17"])
    return pd.DataFrame(
        {
            "t_min_celsius": [10.0, -3.0, 5.0],
            "t_max_celsius": [22.0, 18.0, 35.0],
            "pluie_24h_mm": [0.0, 25.0, 5.0],
            "rafales_max_kmh": [30.0, 50.0, 75.0],
            "etp_mm": [3.5, 1.0, 4.2],
            "bilan_eau_cumul_mm": [-3.5, 20.5, 21.3],
        },
        index=dates,
    )


def test_libelle_mapping() -> None:
    from apps.operationnelle.ui_helpers import libelle

    assert libelle("t_min_celsius") == "T° min (°C)"
    assert libelle("inconnu") == "inconnu"


def test_preparer_table_renomme_et_arrondit() -> None:
    from apps.operationnelle.ui_helpers import preparer_table_affichage

    df = _quotidien_synth()
    df["etp_mm"] = [3.567, 1.012, 4.245]  # forcer arrondi
    table = preparer_table_affichage(df)
    assert "T° min (°C)" in table.columns
    assert "ETP (mm)" in table.columns
    # Précision 1 décimale.
    assert table["ETP (mm)"].iloc[0] == 3.6


def test_styler_ligne_gel() -> None:
    from apps.operationnelle.ui_helpers import preparer_table_affichage, styler_ligne

    df = _quotidien_synth()
    table = preparer_table_affichage(df)
    # Ligne 2 : t_min = -3 → alerte gel.
    styles = styler_ligne(table.iloc[1], ALERTES_TEST)
    cols = list(table.columns)
    assert "background-color" in styles[cols.index("T° min (°C)")]
    # Pas de canicule sur cette ligne.
    assert styles[cols.index("T° max (°C)")] == ""


def test_styler_ligne_canicule_pluie_vent() -> None:
    from apps.operationnelle.ui_helpers import preparer_table_affichage, styler_ligne

    df = _quotidien_synth()
    table = preparer_table_affichage(df)
    # Ligne 3 : t_max = 35 → canicule ; rafales = 75 → vent fort ;
    # pluie 5 → pas d'alerte pluie.
    styles = styler_ligne(table.iloc[2], ALERTES_TEST)
    cols = list(table.columns)
    assert "background-color" in styles[cols.index("T° max (°C)")]
    assert "background-color" in styles[cols.index("Rafales (km/h)")]
    assert styles[cols.index("Pluie 24 h (mm)")] == ""


def test_styler_ligne_pluie_intense() -> None:
    from apps.operationnelle.ui_helpers import preparer_table_affichage, styler_ligne

    df = _quotidien_synth()
    table = preparer_table_affichage(df)
    # Ligne 2 : pluie = 25 → intense.
    styles = styler_ligne(table.iloc[1], ALERTES_TEST)
    cols = list(table.columns)
    assert "background-color" in styles[cols.index("Pluie 24 h (mm)")]


def test_styler_ligne_alerte_inactive() -> None:
    from apps.operationnelle.ui_helpers import preparer_table_affichage, styler_ligne

    df = _quotidien_synth()
    table = preparer_table_affichage(df)
    config_off = {**ALERTES_TEST}
    config_off["gel"] = {"actif": False, "seuil_celsius": -2.0}
    styles = styler_ligne(table.iloc[1], config_off)
    cols = list(table.columns)
    # Pas de style même si t_min < -2.
    assert styles[cols.index("T° min (°C)")] == ""
