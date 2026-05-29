"""Tests `apps.operationnelle.charts` — figures Op (smoke + structure)."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # backend headless avant import pyplot

import pandas as pd
import pytest

from apps.operationnelle.charts import (
    COURBES,
    CourbeConfig,
    figure_bilan_culture,
    figure_indicateur,
)


@pytest.fixture
def quotidien_synth() -> pd.DataFrame:
    """DataFrame quotidien synthétique de 7 jours avec normales."""
    idx = pd.date_range("2026-05-29", periods=7, freq="D")
    return pd.DataFrame(
        {
            "t_min_celsius": [10.0, 11.0, 12.0, 11.5, 9.0, 10.5, 11.0],
            "t_max_celsius": [18.0, 20.0, 22.0, 21.0, 17.0, 19.0, 20.0],
            "t_moy_celsius": [14.0, 15.5, 17.0, 16.2, 13.0, 14.7, 15.5],
            "t_min_normale_celsius": [9.5, 9.6, 9.7, 9.8, 9.9, 10.0, 10.1],
            "t_max_normale_celsius": [19.0, 19.1, 19.2, 19.3, 19.4, 19.5, 19.6],
            "t_moy_normale_celsius": [14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8],
            "pluie_24h_mm": [0.0, 2.5, 5.0, 1.0, 0.0, 8.0, 3.0],
            "etp_mm": [3.0, 3.5, 4.0, 3.8, 2.5, 3.2, 3.5],
            "bilan_eau_cumul_mm": [-3.0, -4.0, -3.0, -5.8, -8.3, -3.5, -4.0],
            "rafales_max_kmh": [25.0, 30.0, 40.0, 35.0, 28.0, 32.0, 30.0],
            "mildiou_heures_hr_haute": [4, 8, 12, 6, 2, 10, 5],
        },
        index=idx,
    )


def test_courbes_config_couvre_indicateurs_attendus() -> None:
    cols = {c.colonne for c in COURBES}
    for attendu in ("t_min_celsius", "t_max_celsius", "t_moy_celsius", "pluie_24h_mm", "etp_mm"):
        assert attendu in cols, f"COURBES devrait inclure {attendu}"


def test_figure_indicateur_t_moy_avec_normale(quotidien_synth: pd.DataFrame) -> None:
    cfg = next(c for c in COURBES if c.colonne == "t_moy_celsius")
    fig = figure_indicateur(quotidien_synth, cfg)
    ax = fig.axes[0]
    # Trois lignes attendues : prévision, normale + 2 zones shade.
    handles, labels = ax.get_legend_handles_labels()
    assert "Prévision" in labels
    assert any("Normale" in lbl for lbl in labels)
    assert any("Au-dessus" in lbl for lbl in labels) or any("En-dessous" in lbl for lbl in labels)


def test_figure_indicateur_sans_normale_ne_dessine_pas_overlay(
    quotidien_synth: pd.DataFrame,
) -> None:
    cfg = CourbeConfig(colonne="rafales_max_kmh", titre="Test", unite="km/h", couleur="#000000")
    fig = figure_indicateur(quotidien_synth, cfg)
    ax = fig.axes[0]
    _handles, labels = ax.get_legend_handles_labels()
    assert "Prévision" in labels
    # Pas de mention "Normale" puisque colonne_normale est None.
    assert not any("Normale" in lbl for lbl in labels)


def test_figure_bilan_culture_genere_2_courbes(quotidien_synth: pd.DataFrame) -> None:
    fig = figure_bilan_culture(quotidien_synth, culture="Tomate", stade="Plein", kc=1.0)
    ax = fig.axes[0]
    _handles, labels = ax.get_legend_handles_labels()
    assert any("Pluie cumulée" in lbl for lbl in labels)
    assert any("ET_c cumulée" in lbl for lbl in labels)


def test_figure_indicateur_seuil_affiche_si_courbe_traverse(
    quotidien_synth: pd.DataFrame,
) -> None:
    """Quotidien synth T_min 9-12 °C traverse 10 °C → seuil affiché."""
    cfg = next(c for c in COURBES if c.colonne == "t_min_celsius")
    fig = figure_indicateur(quotidien_synth, cfg)
    ax = fig.axes[0]
    _, labels = ax.get_legend_handles_labels()
    assert any("Seuil biologique" in lbl for lbl in labels)


def test_figure_indicateur_seuil_masque_si_courbe_ne_traverse_pas() -> None:
    """T_min toute la fenêtre au-dessus de 10 °C → pas de seuil affiché."""
    idx = pd.date_range("2026-07-01", periods=7, freq="D")
    df = pd.DataFrame(
        {
            "t_min_celsius": [14.0, 15.0, 16.0, 14.5, 15.5, 14.8, 15.2],
            "t_min_normale_celsius": [13.0, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6],
        },
        index=idx,
    )
    cfg = next(c for c in COURBES if c.colonne == "t_min_celsius")
    fig = figure_indicateur(df, cfg)
    ax = fig.axes[0]
    _, labels = ax.get_legend_handles_labels()
    assert not any("Seuil biologique" in lbl for lbl in labels)


def test_figure_indicateur_mildiou_hr_seuil_et_min_glissant(
    quotidien_synth: pd.DataFrame,
) -> None:
    """Onglet HR ≥ 90 % : seuil 11 h + min glissant 2 j présents."""
    cfg = next(c for c in COURBES if c.colonne == "mildiou_heures_hr_haute")
    fig = figure_indicateur(quotidien_synth, cfg)
    ax = fig.axes[0]
    _, labels = ax.get_legend_handles_labels()
    assert any("Seuil Smith" in lbl for lbl in labels)
    assert any("Min glissant" in lbl for lbl in labels)


def test_figure_bilan_culture_kc_zero_etc_constant_zero(
    quotidien_synth: pd.DataFrame,
) -> None:
    fig = figure_bilan_culture(quotidien_synth, culture="Test", stade="Test", kc=0.0)
    ax = fig.axes[0]
    lignes = [line for line in ax.get_lines() if "ET_c" in (line.get_label() or "")]
    assert lignes
    ydata = lignes[0].get_ydata()
    # Avec Kc=0, ET_c = 0 partout → cumul constant à 0.
    assert (ydata == 0).all()
