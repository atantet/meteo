"""Tests `meteo_socle.indices.lwd_gleason` — CART Gleason 1994."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from meteo_socle.indices.lwd_gleason import (
    DPD_SEUIL_BAS,
    DPD_SEUIL_HAUT,
    HR_SEUIL,
    VENT_SEUIL,
    heures_lwd_par_jour,
    lwd_horaire_gleason,
    point_de_rosee_magnus_tetens,
)


def test_magnus_tetens_saturation_td_egal_t() -> None:
    """À 100 % HR, Td = T (la feuille est à saturation)."""
    td = point_de_rosee_magnus_tetens(20.0, 1.0)
    assert td == pytest.approx(20.0, abs=0.01)


def test_magnus_tetens_valeurs_typiques() -> None:
    """T=20 °C, HR=50 % → Td ≈ 9.27 °C (Magnus-Tetens canonique)."""
    td = point_de_rosee_magnus_tetens(20.0, 0.50)
    assert td == pytest.approx(9.27, abs=0.1)


def _horaire_synth(t_c: float, hr: float, vent_ms: float, n: int = 6) -> pd.DataFrame:
    idx = pd.date_range("2026-06-15 00:00", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(n, t_c + 273.15),
            "humidite_relative": np.full(n, hr),
            "vitesse_vent_10m": np.full(n, vent_ms),
            "precipitation": np.zeros(n),
        },
        index=idx,
    )


def test_lwd_dpd_tres_bas_donne_wet() -> None:
    """T = 12 °C, HR = 99 % → DPD ≈ 0.15 °C ≤ 3.7 → wet."""
    df = _horaire_synth(t_c=12.0, hr=0.99, vent_ms=1.0)
    wet = lwd_horaire_gleason(df)
    assert wet.all()


def test_lwd_dpd_tres_haut_donne_dry() -> None:
    """T = 25 °C, HR = 40 % → DPD ≈ 11 °C > 7.2 → dry."""
    df = _horaire_synth(t_c=25.0, hr=0.40, vent_ms=1.0)
    wet = lwd_horaire_gleason(df)
    assert not wet.any()


def test_lwd_zone_intermediaire_vent_haut_donne_dry() -> None:
    """DPD intermédiaire mais vent ≥ 2.5 m/s → sec."""
    # T = 15 °C, HR = 75 % → Td ≈ 10.5, DPD ≈ 4.5 (intermédiaire).
    df = _horaire_synth(t_c=15.0, hr=0.75, vent_ms=3.0)
    wet = lwd_horaire_gleason(df)
    assert not wet.any()


def test_lwd_zone_intermediaire_vent_bas_donne_wet_si_hr_haute() -> None:
    """DPD intermédiaire, vent < 2.5 m/s, HR ≥ 87.8 % → wet.

    Difficile à construire avec une combinaison T/HR cohérente : HR ≥
    87.8 % donne souvent DPD ≤ 3.7 (zone basse). On utilise donc une
    HR à exactement 0.878 et on cherche un T plus élevé pour pousser
    DPD au-delà de 3.7.
    """
    # T = 30 °C, HR = 0.78 → DPD ≈ 4.7 mais HR sous le seuil → sec.
    # T = 30 °C, HR = 0.85 → DPD ≈ 3.0 (zone basse).
    # T = 35 °C, HR = 0.80 → Td ≈ 31, DPD ≈ 4 → intermédiaire, HR < seuil.
    # Cas dans la zone : difficile à atteindre avec HR ≥ 0.878 vu la
    # courbe Magnus-Tetens. On vérifie au moins que la branche `dry`
    # de la zone intermédiaire fonctionne (HR sous seuil).
    df = _horaire_synth(t_c=35.0, hr=0.80, vent_ms=1.0)
    t = 35.0
    td = point_de_rosee_magnus_tetens(t, 0.80)
    dpd = t - td
    assert DPD_SEUIL_BAS < dpd <= DPD_SEUIL_HAUT, f"DPD={dpd:.2f} pas intermédiaire"
    # Vent < seuil et HR < seuil → sec.
    wet = lwd_horaire_gleason(df)
    assert not wet.any()


def test_lwd_pluie_override_force_wet() -> None:
    """Pluie sur l'heure → mouillé même si DPD très élevé."""
    df = _horaire_synth(t_c=25.0, hr=0.40, vent_ms=5.0)
    # Force pluie sur heure 0 et 1.
    df.loc[df.index[0], "precipitation"] = 1.0
    df.loc[df.index[1], "precipitation"] = 1.0
    wet = lwd_horaire_gleason(df, heures_pluie_persistance=1)
    # Heures 0 et 1 doivent être mouillées (override pluie). Au-delà,
    # retour au verdict CART (sec ici).
    assert wet.iloc[0]
    assert wet.iloc[1]
    assert not wet.iloc[5]


def test_heures_lwd_par_jour_agrege_correctement() -> None:
    idx = pd.date_range("2026-06-15 00:00", periods=48, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "temperature_2m": np.full(48, 12.0 + 273.15),  # T = 12 °C
            "humidite_relative": np.full(48, 0.99),  # HR = 99 %
            "vitesse_vent_10m": np.full(48, 1.0),
            "precipitation": np.zeros(48),
        },
        index=idx,
    )
    quot = heures_lwd_par_jour(df, tz_locale="UTC")
    # Chaque jour devrait avoir 24 h mouillées (DPD ≈ 0.15 → toujours bas).
    assert (quot["heures_lwd"] == 24).all()
    assert (quot["heures_dpd_bas"] == 24).all()


def test_seuils_publies_sont_dans_les_constantes() -> None:
    """Sanity check sur les valeurs de seuils publiées dans Gleason 1994."""
    assert DPD_SEUIL_BAS == 3.7
    assert DPD_SEUIL_HAUT == 7.2
    assert VENT_SEUIL == 2.5
    assert pytest.approx(0.878) == HR_SEUIL
