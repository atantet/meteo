"""Tests `apps.veille.indicateurs` — calculs sur prévision synthétique."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


CONFIG_TEST = {
    "indicateurs": {
        "bilan_eau": {
            "tension_irrigation": {
                "seuil_etp_seche_mm": 5.0,
                "seuil_pluie_compense_mm": 2.0,
                "seuil_deficit_7j_mm": -15.0,
            }
        }
    }
}


def _prevision_synthetique(
    duree_h: int = 168,
    t_celsius: float = 15.0,
    pluie_horaire_mm: float = 0.0,
    vent_ms: float = 5.0,
    rafales_ms: float = 9.0,
    etp_horaire_mm: float = 0.1,
) -> pd.DataFrame:
    """Construit une prévision horaire homogène pour tests."""
    index = pd.date_range("2024-06-15 00:00:00+00:00", periods=duree_h, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(duree_h, t_celsius + 273.15),
            "precipitation": np.full(duree_h, pluie_horaire_mm),
            "vitesse_vent_10m": np.full(duree_h, vent_ms),
            "rafales_vent_10m": np.full(duree_h, rafales_ms),
            "etp_open_meteo": np.full(duree_h, etp_horaire_mm),
        },
        index=index,
    )


def test_calculer_indicateurs_basique() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_TEST)

    # T° homogène à 15 °C → min = max = 15.
    assert ind.temperature_min_24h_celsius == pytest.approx(15.0)
    assert ind.temperature_max_24h_celsius == pytest.approx(15.0)
    # Cumul pluie 0 → 0.
    assert ind.cumul_pluie_24h_mm == pytest.approx(0.0)
    # Vent : 5 m/s × 3.6 = 18 km/h.
    assert ind.vent_max_24h_kmh == pytest.approx(18.0)
    # Rafales : 9 m/s × 3.6 = 32.4 km/h.
    assert ind.rafales_max_24h_kmh == pytest.approx(32.4)
    # ETP : 0.1 mm/h × 24 h = 2.4 mm/jour.
    assert ind.etp_jour_mm == pytest.approx(2.4)
    # Bilan eau 7j : 0 pluie - 0.1×168 etp = −16.8 mm.
    assert ind.bilan_eau_7j_mm == pytest.approx(-16.8)


def test_calculer_indicateurs_alerte_gel_canicule() -> None:
    """Variation T° dans les 24h prochaines → min nuit / max jour distinctes."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    # Modifie les 24 premières heures pour simuler un cycle nuit (froid) →
    # jour (chaud) → nuit (froid).
    t_pattern = [-3.0] * 8 + [20.0] * 8 + [-1.0] * 8
    prevision.loc[prevision.index[:24], "temperature_2m"] = np.array(t_pattern) + 273.15
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.temperature_min_24h_celsius == pytest.approx(-3.0)
    assert ind.temperature_max_24h_celsius == pytest.approx(20.0)


def test_calculer_indicateurs_cumuls_pluie() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(pluie_horaire_mm=1.0)
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    # 1 mm × 24h = 24 mm sur 24h, 48 sur 48h, 72 sur 72h.
    assert ind.cumul_pluie_24h_mm == pytest.approx(24.0)
    assert ind.cumul_pluie_48h_mm == pytest.approx(48.0)
    assert ind.cumul_pluie_72h_mm == pytest.approx(72.0)


def test_calculer_indicateurs_tension_irrigation_declenchee() -> None:
    """ETP forte + pluie nulle + déficit accumulé → tension_irrigation True."""
    from apps.veille.indicateurs import calculer_indicateurs

    # ETP 0.4 mm/h × 24 h = 9.6 mm/jour > seuil 5 ; pluie 0 ; bilan 7j
    # = 0 − 0.4×168 = −67.2 < seuil −15.
    prevision = _prevision_synthetique(pluie_horaire_mm=0.0, etp_horaire_mm=0.4)
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.tension_irrigation is True


def test_calculer_indicateurs_tension_irrigation_pluie_compense() -> None:
    """ETP forte mais pluie 24h suffisante → pas de tension."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(pluie_horaire_mm=0.5, etp_horaire_mm=0.4)
    # Pluie 24h = 12 mm > seuil 2 mm → la 2ème condition tombe.
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.tension_irrigation is False


def test_calculer_indicateurs_filtre_past() -> None:
    """Les heures antérieures à now sont ignorées."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(duree_h=48, t_celsius=15.0)
    # 24 premières heures à −10 °C, suivantes à 15 °C. now au début du
    # 2ème jour → on ignore le froid.
    prevision.loc[prevision.index[:24], "temperature_2m"] = -10.0 + 273.15
    now = pd.Timestamp("2024-06-16 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.temperature_min_24h_celsius == pytest.approx(15.0)


def test_calculer_indicateurs_vide_raise() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(duree_h=24)
    # now placé après la fin de la prévision.
    now = pd.Timestamp("2024-06-30 00:00:00+00:00")
    with pytest.raises(ValueError):
        calculer_indicateurs(prevision, now, CONFIG_TEST)
