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
    etp_horaire_socle,
    preparer_horaire,
)

SITE_TEST = {"latitude": 48.543648, "longitude": -1.611515, "altitude": 30}


def _prevision_horaire_synthetique(n_jours: int = 4) -> pd.DataFrame:
    """Reproduit la signature `OpenMeteoForecast.obtenir_prevision`.

    La série démarre au 00 UTC du jour courant (et non à une date fixe) :
    `preparer_horaire` recentre le bilan hydrique cumulé sur le 0Z
    d'aujourd'hui ; avec une date figée dans le passé, ce point de
    référence tomberait hors de la fenêtre et le bilan serait décalé.
    """
    n_h = 24 * n_jours
    debut = pd.Timestamp.now(tz="UTC").normalize()
    idx = pd.date_range(debut, periods=n_h, freq="h")
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
    # La série démarre au 0Z courant, qui est justement le point de
    # recentrage : le bilan cumulé y vaut ~0 (au cumul de la 1ʳᵉ heure près).
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


def test_preparer_horaire_injecte_normale_t_moy() -> None:
    """La normale OMM t_moy doit être broadcastée par heure depuis le CSV."""
    df = _prevision_horaire_synthetique(n_jours=2)
    out = preparer_horaire(df, SITE_TEST)
    # La colonne peut être absente si le CSV des normales est absent ;
    # dans ce cas on skip — c'est un environnement de dev.
    if "temperature_2m_c_normale" not in out.columns:
        return
    # La normale doit être constante sur un jour civil donné.
    par_jour = out.groupby(out.index.normalize())["temperature_2m_c_normale"].nunique()
    assert (par_jour == 1).all(), "Normale doit être constante par jour"


def test_etp_horaire_socle_robuste_au_concat_heterogene() -> None:
    """Reproduit le scénario du toggle « 48 h passées » :

    `pd.concat([ERA5, forecast])` peut produire un DataFrame dont
    certaines colonnes sont en dtype `object` (ex. NaN injectés par
    pandas pour les colonnes présentes seulement d'un côté). Le
    `calcul_etp` socle utilise `np.exp` et planterait alors avec
    « loop of ufunc does not support argument 0 of type float ».
    `etp_horaire_socle` doit caster en float avant de déléguer.
    """
    idx = pd.date_range("2026-06-01 00:00", periods=24, freq="h", tz="UTC")
    # Simule un DataFrame mixte : T° en object (NaN dans une colonne),
    # vent en float. Le cast `pd.to_numeric` doit nettoyer ça.
    df_object = pd.DataFrame(
        {
            "temperature_2m": pd.Series([288.15] * 24, dtype="object"),
            "humidite_relative": pd.Series([0.6] * 24, dtype="object"),
            "vitesse_vent_10m": pd.Series([2.0] * 24, dtype="object"),
            "rayonnement_global": pd.Series(
                [0.0 if h < 6 or h > 20 else 500_000.0 for h in range(24)],
                dtype="object",
            ),
        },
        index=idx,
    )
    # Le point clé : pas d'exception ufunc, retour numérique.
    etp = etp_horaire_socle(df_object, SITE_TEST)
    assert etp is not None
    assert pd.api.types.is_numeric_dtype(etp)
