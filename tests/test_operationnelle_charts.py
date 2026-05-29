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


def test_figure_indicateur_seuils_extra_appliques(
    quotidien_synth: pd.DataFrame,
) -> None:
    """Un seuil_extra traversé doit apparaître dans la légende."""
    from apps.operationnelle.charts import Seuil

    cfg = next(c for c in COURBES if c.colonne == "t_max_celsius")
    # T_max va de 17 à 22 °C dans le synth → seuil 20 traversé.
    fig = figure_indicateur(
        quotidien_synth, cfg, seuils_extra=[Seuil(20.0, "Test canicule", "#c0392b")]
    )
    ax = fig.axes[0]
    _, labels = ax.get_legend_handles_labels()
    assert any("Test canicule" in lbl for lbl in labels)


def test_figure_indicateur_seuils_extra_masques_si_hors_range(
    quotidien_synth: pd.DataFrame,
) -> None:
    from apps.operationnelle.charts import Seuil

    cfg = next(c for c in COURBES if c.colonne == "t_max_celsius")
    # Seuil 50 °C jamais traversé.
    fig = figure_indicateur(
        quotidien_synth, cfg, seuils_extra=[Seuil(50.0, "Hors range", "#c0392b")]
    )
    ax = fig.axes[0]
    _, labels = ax.get_legend_handles_labels()
    assert not any("Hors range" in lbl for lbl in labels)


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


def test_bilan_culture_plein_air_pluie_evite_irrigation() -> None:
    """Plein air : pluie suffisante évite l'irrigation alors que tunnel l'aurait déclenchée."""
    from apps.operationnelle.charts import (
        bilan_culture_carry_over,
        bilan_tunnel_carry_over,
    )

    idx = pd.date_range("2026-07-01", periods=5, freq="D")
    # ETP 5 mm + pluie 5 mm → bilan net nul jour à jour.
    df = pd.DataFrame({"etp_mm": [5.0] * 5, "pluie_24h_mm": [5.0] * 5}, index=idx)
    kwargs = dict(
        texture="Terres limono-argileuses",
        fraction_cailloux=0.05,
        culture="Tomate",
        stade="De la plantation à la reprise",  # Kc 0.5
        fraction_ru_remplie_initial=0.7,
        ru_vers_rfu=0.6,
        seuil_irrigation_mm=5.0,
    )
    plein_air = bilan_culture_carry_over(df, k_etp_ratio=1.0, inclure_pluie=True, **kwargs)
    tunnel = bilan_tunnel_carry_over(df, k_tunnel=1.0, **kwargs)
    # Plein air bénéficie de la pluie ; tunnel pas. → moins de déclenchements.
    assert int(plein_air["irrigation_declenchee"].sum()) <= int(
        tunnel["irrigation_declenchee"].sum()
    )
    # Colonne pluie correctement renseignée.
    assert (plein_air["pluie_mm"] == 5.0).all()


def test_bilan_culture_plein_air_secheresse_declenche_irrigation() -> None:
    """Plein air sans pluie + ETM forte → irrigation déclenchée."""
    from apps.operationnelle.charts import bilan_culture_carry_over

    idx = pd.date_range("2026-07-01", periods=5, freq="D")
    df = pd.DataFrame({"etp_mm": [8.0] * 5, "pluie_24h_mm": [0.0] * 5}, index=idx)
    bilan = bilan_culture_carry_over(
        df,
        texture="Terres sablo-argileuses",  # RU plus faible
        fraction_cailloux=0.0,
        culture="Tomate",
        stade="De la floraison du 3ème bouquet à la mi-récolte",  # Kc 1.0
        fraction_ru_remplie_initial=0.6,
        ru_vers_rfu=0.6,
        seuil_irrigation_mm=5.0,
        k_etp_ratio=1.0,
        inclure_pluie=True,
    )
    assert bilan["irrigation_declenchee"].any()


def test_bilan_culture_pluie_excedentaire_ne_depasse_pas_ru_max() -> None:
    """Pluie >> ETM → RU plafonnée à ru_max (drainage)."""
    from apps.operationnelle.charts import bilan_culture_carry_over

    idx = pd.date_range("2026-07-01", periods=3, freq="D")
    # Pluie 100 mm/j (déluge) — devrait être tronquée à ru_max.
    df = pd.DataFrame({"etp_mm": [3.0] * 3, "pluie_24h_mm": [100.0] * 3}, index=idx)
    bilan = bilan_culture_carry_over(
        df,
        texture="Terres limono-argileuses",
        fraction_cailloux=0.05,
        culture="Tomate",
        stade="De la plantation à la reprise",
        fraction_ru_remplie_initial=0.5,
        ru_vers_rfu=0.6,
        seuil_irrigation_mm=10.0,
        k_etp_ratio=1.0,
        inclure_pluie=True,
    )
    assert (bilan["ru_remplie_apres_mm"] <= bilan["ru_max_mm"]).all()


def test_bilan_tunnel_carry_over_decroit_ru_si_pas_irrigation() -> None:
    """Sans déclenchement, la RU décroît jour après jour (etp positive)."""
    from apps.operationnelle.charts import bilan_tunnel_carry_over

    idx = pd.date_range("2026-07-01", periods=5, freq="D")
    # Pluie 0 (ignorée sous tunnel) + ETP constante.
    df = pd.DataFrame({"etp_mm": [3.0] * 5, "pluie_24h_mm": [0.0] * 5}, index=idx)
    bilan = bilan_tunnel_carry_over(
        df,
        k_tunnel=0.7,
        texture="Terres limoneuses",
        fraction_cailloux=0.0,
        culture="Tomate",
        stade="De la plantation à la reprise",
        fraction_ru_remplie_initial=1.0,
        ru_vers_rfu=0.6,
        # Seuil très haut → jamais déclenché.
        seuil_irrigation_mm=999.0,
    )
    ru_serie = bilan["ru_remplie_avant_mm"].to_numpy()
    # RU strictement décroissante (pas de pluie, pas d'irrigation).
    assert all(ru_serie[i] > ru_serie[i + 1] for i in range(len(ru_serie) - 1))


def test_bilan_tunnel_carry_over_recharge_si_seuil_franchi() -> None:
    """Si le besoin dépasse le seuil, irrigation déclenchée → RU rechargée."""
    from apps.operationnelle.charts import bilan_tunnel_carry_over

    idx = pd.date_range("2026-07-01", periods=5, freq="D")
    df = pd.DataFrame({"etp_mm": [10.0] * 5, "pluie_24h_mm": [0.0] * 5}, index=idx)
    bilan = bilan_tunnel_carry_over(
        df,
        k_tunnel=1.0,
        texture="Terres sableuses",  # RU faible → s'épuise vite
        fraction_cailloux=0.0,
        culture="Tomate",
        stade="De la plantation à la reprise",
        fraction_ru_remplie_initial=0.5,
        ru_vers_rfu=0.6,
        seuil_irrigation_mm=1.0,  # seuil bas → déclenche vite
    )
    assert bilan["irrigation_declenchee"].any()


def test_figure_bilan_tunnel_smoke() -> None:
    """La figure tunnel se rend sans erreur sur une RU plausible."""
    from apps.operationnelle.charts import (
        bilan_tunnel_carry_over,
        figure_bilan_tunnel,
    )

    idx = pd.date_range("2026-07-01", periods=7, freq="D")
    df = pd.DataFrame({"etp_mm": [4.0] * 7, "pluie_24h_mm": [0.0] * 7}, index=idx)
    bilan = bilan_tunnel_carry_over(
        df,
        k_tunnel=0.7,
        texture="Terres limono-argileuses",
        fraction_cailloux=0.05,
        culture="Tomate",
        stade="De la plantation à la reprise",
        fraction_ru_remplie_initial=0.7,
        ru_vers_rfu=0.6,
        seuil_irrigation_mm=10.0,
    )
    fig = figure_bilan_tunnel(bilan, culture="Tomate", stade="X", seuil_irrigation_mm=10.0)
    ax = fig.axes[0]
    _, labels = ax.get_legend_handles_labels()
    assert any("RU disponible" in lbl for lbl in labels)
    assert any("Seuil irrigation" in lbl for lbl in labels)


def test_bilan_tunnel_ru_initiale_zero_declenche_irrigation_immediate() -> None:
    """RU initiale = 0 → besoin immédiat dès le premier jour avec ETP > 0."""
    from apps.operationnelle.charts import bilan_tunnel_carry_over

    idx = pd.date_range("2026-07-01", periods=3, freq="D")
    df = pd.DataFrame({"etp_mm": [3.0] * 3, "pluie_24h_mm": [0.0] * 3}, index=idx)
    bilan = bilan_tunnel_carry_over(
        df,
        k_tunnel=0.7,
        texture="Terres limono-argileuses",
        fraction_cailloux=0.05,
        culture="Tomate",
        stade="De la plantation à la reprise",
        fraction_ru_remplie_initial=0.0,
        ru_vers_rfu=0.6,
        seuil_irrigation_mm=1.0,
    )
    # Premier jour : besoin déjà > seuil → irrigation déclenchée jour 0.
    assert bilan["irrigation_declenchee"].iloc[0]


def test_bilan_tunnel_k_tunnel_zero_pas_d_etm_evolutif() -> None:
    """k_tunnel = 0 → ETM = 0. RU initialement pleine → reste pleine (pas
    de besoin), donc pas de déclenchement."""
    from apps.operationnelle.charts import bilan_tunnel_carry_over

    idx = pd.date_range("2026-07-01", periods=5, freq="D")
    df = pd.DataFrame({"etp_mm": [5.0] * 5, "pluie_24h_mm": [0.0] * 5}, index=idx)
    bilan = bilan_tunnel_carry_over(
        df,
        k_tunnel=0.0,
        texture="Terres limono-argileuses",
        fraction_cailloux=0.05,
        culture="Tomate",
        stade="De la plantation à la reprise",
        fraction_ru_remplie_initial=1.0,
        ru_vers_rfu=0.6,
        seuil_irrigation_mm=10.0,
    )
    # ETM nulle.
    assert (bilan["etm_tunnel_mm"] == 0).all()
    # RU pleine ne décroît pas → pas d'irrigation déclenchée.
    assert not bilan["irrigation_declenchee"].any()
    # RU reste à capacité = constante.
    assert bilan["ru_remplie_avant_mm"].nunique() == 1


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
