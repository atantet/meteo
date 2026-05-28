"""Tests `apps.veille.indicateurs` — calculs sur prévision synthétique."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


CONFIG_TEST = {
    # Site = Pleine-Fougères (cf. ADR-0001 règle 3) — utile pour calcul_etp.
    "site": {"latitude": 48.5420, "longitude": -1.6155, "altitude": 30},
    "indicateurs": {
        "bilan_eau": {
            "tension_irrigation": {
                "seuil_etp_seche_mm": 5.0,
                "seuil_pluie_compense_mm": 2.0,
                "seuil_deficit_7j_mm": -15.0,
            }
        }
    },
}


def _prevision_synthetique(
    duree_h: int = 168,
    t_celsius: float = 15.0,
    pluie_horaire_mm: float = 0.0,
    vent_ms: float = 5.0,
    rafales_ms: float = 9.0,
    humidite: float = 0.7,
    rayonnement_jh: float = 0.0,
) -> pd.DataFrame:
    """Construit une prévision horaire homogène pour tests."""
    index = pd.date_range("2024-06-15 00:00:00+00:00", periods=duree_h, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(duree_h, t_celsius + 273.15),
            "humidite_relative": np.full(duree_h, humidite),
            "vitesse_vent_10m": np.full(duree_h, vent_ms),
            "rafales_vent_10m": np.full(duree_h, rafales_ms),
            "rayonnement_global": np.full(duree_h, rayonnement_jh),
            "precipitation": np.full(duree_h, pluie_horaire_mm),
        },
        index=index,
    )


def _patch_etp(etp_horaire_mm: float):
    """Helper : mock `apps.veille.indicateurs.calcul_etp` pour valeur constante."""

    def fake_calcul_etp(df, lat, lon, alt):
        return pd.Series(etp_horaire_mm, index=df.index)

    return patch("apps.veille.indicateurs.calcul_etp", side_effect=fake_calcul_etp)


def test_calculer_indicateurs_basique() -> None:
    """ETP mockée à 0.1 mm/h constante — vérifie les sommes et conversions."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with _patch_etp(0.1):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)

    assert ind.temperature_min_24h_celsius == pytest.approx(15.0)
    assert ind.temperature_max_24h_celsius == pytest.approx(15.0)
    assert ind.cumul_pluie_24h_mm == pytest.approx(0.0)
    assert ind.vent_max_24h_kmh == pytest.approx(18.0)  # 5 m/s × 3.6
    assert ind.rafales_max_24h_kmh == pytest.approx(32.4)  # 9 m/s × 3.6
    # ETP mockée : 0.1 mm/h × 24 = 2.4 mm/j ; × 168 = 16.8 mm sur 7j.
    assert ind.etp_jour_mm == pytest.approx(2.4)
    assert ind.bilan_eau_7j_mm == pytest.approx(-16.8)


def test_calculer_indicateurs_alerte_gel_canicule() -> None:
    """Variation T° dans les 24h prochaines → min nuit / max jour distinctes."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    t_pattern = [-3.0] * 8 + [20.0] * 8 + [-1.0] * 8
    prevision.loc[prevision.index[:24], "temperature_2m"] = np.array(t_pattern) + 273.15
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with _patch_etp(0.1):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.temperature_min_24h_celsius == pytest.approx(-3.0)
    assert ind.temperature_max_24h_celsius == pytest.approx(20.0)


def test_calculer_indicateurs_cumuls_pluie() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(pluie_horaire_mm=1.0)
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with _patch_etp(0.0):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.cumul_pluie_24h_mm == pytest.approx(24.0)
    assert ind.cumul_pluie_48h_mm == pytest.approx(48.0)
    assert ind.cumul_pluie_72h_mm == pytest.approx(72.0)


def test_calculer_indicateurs_tension_irrigation_declenchee() -> None:
    """ETP forte + pluie nulle + déficit accumulé → tension_irrigation True."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(pluie_horaire_mm=0.0)
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    # ETP mockée à 0.4 mm/h → 9.6 mm/j, bilan 7j = −67.2 mm.
    with _patch_etp(0.4):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.tension_irrigation is True


def test_calculer_indicateurs_tension_irrigation_pluie_compense() -> None:
    """ETP forte mais pluie 24h suffisante → pas de tension."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(pluie_horaire_mm=0.5)
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with _patch_etp(0.4):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.tension_irrigation is False


def test_calculer_indicateurs_filtre_past() -> None:
    """Les heures antérieures à now sont ignorées."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(duree_h=48, t_celsius=15.0)
    prevision.loc[prevision.index[:24], "temperature_2m"] = -10.0 + 273.15
    now = pd.Timestamp("2024-06-16 00:00:00+00:00")
    with _patch_etp(0.1):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.temperature_min_24h_celsius == pytest.approx(15.0)


def test_calculer_indicateurs_vide_raise() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(duree_h=24)
    now = pd.Timestamp("2024-06-30 00:00:00+00:00")
    with pytest.raises(ValueError):
        calculer_indicateurs(prevision, now, CONFIG_TEST)


def test_calculer_indicateurs_etp_socle_appelee() -> None:
    """Smoke test : calcul_etp est appelée avec les bons inputs site."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with patch("apps.veille.indicateurs.calcul_etp") as mock_etp:
        mock_etp.return_value = pd.Series(0.0, index=prevision.head(24).index)
        calculer_indicateurs(prevision, now, CONFIG_TEST)
    # Au moins 2 appels (h24 et h168), avec les coords site Pleine-Fougères.
    assert mock_etp.call_count >= 2
    for call in mock_etp.call_args_list:
        args = call.args
        assert args[1] == pytest.approx(48.5420)  # latitude
        assert args[2] == pytest.approx(-1.6155)  # longitude
        assert args[3] == pytest.approx(30)  # altitude
