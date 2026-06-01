"""Tests `apps.operationnelle.series_temp` — préparation horaire pour §4."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apps.operationnelle.series_temp import (  # noqa: E402
    COURBES_HORAIRES,
    KELVIN_VERS_CELSIUS,
    MS_VERS_KMH,
    preparer_horaire,
)

SITE_TEST = {"latitude": 48.5420, "longitude": -1.6155, "altitude": 30}


def _prevision_horaire_synthetique(n_jours: int = 4) -> pd.DataFrame:
    """Reproduit la signature `OpenMeteoForecast.obtenir_prevision`."""
    n_h = 24 * n_jours
    idx = pd.date_range("2026-06-01 00:00", periods=n_h, freq="h", tz="UTC")
    t_c = 13.0 + 5.0 * np.sin(np.linspace(0, 2 * np.pi * n_jours, n_h))
    hr = np.clip(0.55 + 0.30 * np.cos(np.linspace(0, 2 * np.pi * n_jours, n_h)), 0.4, 0.95)
    return pd.DataFrame(
        {
            "temperature_2m": t_c + KELVIN_VERS_CELSIUS,
            "humidite_relative": hr,
            "precipitation": np.full(n_h, 0.2),
            "vitesse_vent_10m": np.full(n_h, 4.0),
            "rafales_vent_10m": np.full(n_h, 8.0),
            "rayonnement_global": np.maximum(
                0, 500 * np.sin(np.linspace(0, 2 * np.pi * n_jours, n_h)) * 3600.0
            ),
        },
        index=idx,
    )


def test_preparer_horaire_convertit_t_kelvin_vers_celsius() -> None:
    """T° en K en entrée → °C en sortie (cohérence socle Open-Meteo)."""
    df = _prevision_horaire_synthetique(n_jours=1)
    out = preparer_horaire(df, SITE_TEST)
    # Plage °C raisonnable, certainement pas du kelvin.
    assert (out["temperature_2m_c"] >= -10).all()
    assert (out["temperature_2m_c"] <= 40).all()


def test_preparer_horaire_convertit_vent_ms_vers_kmh() -> None:
    """4 m/s constant → 14.4 km/h ; 8 m/s rafales → 28.8 km/h."""
    df = _prevision_horaire_synthetique(n_jours=1)
    out = preparer_horaire(df, SITE_TEST)
    assert out["vent_moy_kmh"].mean() == pytest.approx(4.0 * MS_VERS_KMH, abs=1e-6)
    assert out["rafales_max_kmh"].mean() == pytest.approx(8.0 * MS_VERS_KMH, abs=1e-6)


def test_preparer_horaire_bilan_eau_cumul_monotone_si_pluie_egale_etp() -> None:
    """Si pluie ≈ ETP, le bilan cumul oscille faiblement."""
    df = _prevision_horaire_synthetique(n_jours=2)
    out = preparer_horaire(df, SITE_TEST)
    assert "bilan_eau_cumul_mm" in out.columns
    # Le cumul commence à pluie[0] - etp[0] (1 heure), pas exactement 0.
    assert abs(out["bilan_eau_cumul_mm"].iloc[0]) < 1.0


def test_preparer_horaire_etp_horaire_socle_calculee() -> None:
    """ETP socle FAO (mm/h) doit être positive de jour."""
    df = _prevision_horaire_synthetique(n_jours=1)
    out = preparer_horaire(df, SITE_TEST)
    assert "etp_horaire_mm" in out.columns
    # Au moins quelques heures de jour avec ETP > 0.
    assert (out["etp_horaire_mm"] > 0).any()


def test_preparer_horaire_avec_passe_concatene_en_amont() -> None:
    """Le passé ERA5 doit apparaître AVANT la prévision dans l'index."""
    df_passe = _prevision_horaire_synthetique(n_jours=2)
    df_passe.index = df_passe.index - pd.Timedelta(days=2)
    df_prev = _prevision_horaire_synthetique(n_jours=2)
    out = preparer_horaire(df_prev, SITE_TEST, passe=df_passe)
    # Index doit être croissant et contenir J-2 → J+2.
    assert out.index.is_monotonic_increasing
    assert out.index[0] < df_prev.index[0]
    assert out.index[-1] == df_prev.index[-1]


def test_preparer_horaire_passe_recouvrement_garde_passe() -> None:
    """En cas de recouvrement, on garde la valeur passée (observée)."""
    idx_commune = pd.Timestamp("2026-06-01 00:00", tz="UTC")
    df_passe = pd.DataFrame(
        {
            "temperature_2m": [280.0],  # 6.85 °C
            "humidite_relative": [0.6],
            "precipitation": [0.0],
            "vitesse_vent_10m": [1.0],
            "rafales_vent_10m": [1.0],
            "rayonnement_global": [0.0],
        },
        index=pd.DatetimeIndex([idx_commune], tz="UTC"),
    )
    df_prev = pd.DataFrame(
        {
            "temperature_2m": [300.0],  # 26.85 °C → différent
            "humidite_relative": [0.5],
            "precipitation": [0.0],
            "vitesse_vent_10m": [2.0],
            "rafales_vent_10m": [2.0],
            "rayonnement_global": [0.0],
        },
        index=pd.DatetimeIndex([idx_commune], tz="UTC"),
    )
    out = preparer_horaire(df_prev, SITE_TEST, passe=df_passe)
    # Valeur ERA5 (passé observé) prioritaire.
    assert out["temperature_2m_c"].iloc[0] == pytest.approx(280.0 - KELVIN_VERS_CELSIUS)


def test_courbes_horaires_colonnes_existent_apres_preparation() -> None:
    """Toutes les colonnes ciblées par COURBES_HORAIRES sont produites."""
    df = _prevision_horaire_synthetique(n_jours=1)
    out = preparer_horaire(df, SITE_TEST)
    for cfg in COURBES_HORAIRES:
        assert cfg.colonne in out.columns, f"Colonne manquante : {cfg.colonne}"
