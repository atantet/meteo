"""Tests de la température ressentie (windchill NWS 2001 + humidex Env. Canada)."""

from __future__ import annotations

import pandas as pd
import pytest

from meteo_socle.indices.temperature_ressentie import temperature_ressentie_serie


def _serie(temps_c: list[float], vitesse_ms: list[float], hr_frac: list[float]) -> tuple:
    idx = pd.date_range("2026-01-01", periods=len(temps_c), freq="h", tz="UTC")
    return (
        pd.Series(temps_c, index=idx, dtype=float),
        pd.Series(vitesse_ms, index=idx, dtype=float),
        pd.Series(hr_frac, index=idx, dtype=float),
    )


# --- Windchill ---------------------------------------------------------------


def test_windchill_froid_vent_fort() -> None:
    # T=0 °C, V=10 m/s (36 km/h) → windchill NWS ≈ -7 °C (< 0 °C)
    t, v, rh = _serie([0.0], [10.0], [0.7])
    r = temperature_ressentie_serie(t, v, rh)
    assert r.iloc[0] < 0.0
    assert r.iloc[0] == pytest.approx(-7.05, abs=0.1)


def test_windchill_vent_faible_inchange() -> None:
    # V < 5 km/h (1.2 m/s) → pas de windchill, T inchangée
    t, v, rh = _serie([0.0], [1.2], [0.7])
    r = temperature_ressentie_serie(t, v, rh)
    assert r.iloc[0] == pytest.approx(0.0)


def test_windchill_t_trop_chaude_inchange() -> None:
    # T=12 °C > 10 °C → ni windchill ni humidex (zone neutre)
    t, v, rh = _serie([12.0], [10.0], [0.5])
    r = temperature_ressentie_serie(t, v, rh)
    assert r.iloc[0] == pytest.approx(12.0)


def test_windchill_inferieur_a_t() -> None:
    # Le windchill est toujours ≤ T quand V ≥ 5 km/h.
    t, v, rh = _serie([-5.0, 0.0, 5.0, 10.0], [5.0, 5.0, 5.0, 5.0], [0.7] * 4)
    r = temperature_ressentie_serie(t, v, rh)
    assert (r.values <= t.values + 1e-9).all()


# --- Humidex -----------------------------------------------------------------


def test_humidex_chaleur_humide() -> None:
    # T=30 °C, HR=80 % → humidex ≈ 43 °C (nettement > T)
    t, v, rh = _serie([30.0], [0.5], [0.8])
    r = temperature_ressentie_serie(t, v, rh)
    assert r.iloc[0] > 30.0
    assert r.iloc[0] == pytest.approx(43.3, abs=0.5)


def test_humidex_chaleur_seche_inchange() -> None:
    # T=30 °C, HR=20 % → humidex < T, on affiche T
    t, v, rh = _serie([30.0], [0.5], [0.2])
    r = temperature_ressentie_serie(t, v, rh)
    assert r.iloc[0] == pytest.approx(30.0)


def test_humidex_t_trop_froide_inchange() -> None:
    # T=14 °C < 15 °C, HR=90 % → humidex inactif
    t, v, rh = _serie([14.0], [0.5], [0.9])
    r = temperature_ressentie_serie(t, v, rh)
    assert r.iloc[0] == pytest.approx(14.0)


# --- NaN dans les entrées ----------------------------------------------------


def test_vent_nan_retombe_sur_t() -> None:
    # Vent NaN (heure d'analyse) → windchill non calculable, T retournée
    idx = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    t = pd.Series([0.0], index=idx)
    v = pd.Series([float("nan")], index=idx)
    rh = pd.Series([0.7], index=idx)
    r = temperature_ressentie_serie(t, v, rh)
    assert r.iloc[0] == pytest.approx(0.0)


def test_hr_nan_retombe_sur_t() -> None:
    # HR NaN → humidex non calculable, T retournée
    idx = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    t = pd.Series([30.0], index=idx)
    v = pd.Series([0.5], index=idx)
    rh = pd.Series([float("nan")], index=idx)
    r = temperature_ressentie_serie(t, v, rh)
    assert r.iloc[0] == pytest.approx(30.0)


# --- Série mixte -------------------------------------------------------------


def test_serie_mixte_windchill_neutre_humidex() -> None:
    # Ligne 0 : froid+vent → windchill ; ligne 1 : zone neutre ; ligne 2 : chaleur humide
    t, v, rh = _serie([0.0, 12.0, 30.0], [10.0, 8.0, 0.5], [0.7, 0.6, 0.8])
    r = temperature_ressentie_serie(t, v, rh)
    assert r.iloc[0] < 0.0  # windchill
    assert r.iloc[1] == pytest.approx(12.0)  # neutre
    assert r.iloc[2] > 30.0  # humidex


# --- Unités socle (K → conversion faite par l'appelant) ---------------------


def test_unites_entree_celsius() -> None:
    # La fonction attend des °C, pas des K — vérifier qu'à T=273.15 (=0°C en K)
    # on n'obtient PAS un windchill réaliste (preuve que l'appelant doit convertir).
    t, v, rh = _serie([273.15], [10.0], [0.7])  # T en K par erreur
    r = temperature_ressentie_serie(t, v, rh)
    # Windchill à 273.15 °C et 36 km/h → valeur absurde (>> 100 °C)
    assert r.iloc[0] > 100.0
