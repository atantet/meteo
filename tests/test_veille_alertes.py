"""Tests `apps.veille.alertes` — déclenchements seuils."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


CONFIG_TEST = {
    "alertes": {
        "gel": {"actif": True, "seuil_celsius": -2.0},
        "canicule": {"actif": True, "seuil_celsius": 32.0},
        "pluie_intense": {"actif": True, "seuil_mm_24h": 20.0},
        "vent_fort": {"actif": True, "seuil_kmh": 60.0},
    }
}


def _ind(**kwargs):
    from apps.veille.indicateurs import IndicateursVeille

    defaults = dict(
        temperature_min_24h_celsius=10.0,
        temperature_max_24h_celsius=20.0,
        cumul_pluie_24h_mm=0.0,
        cumul_pluie_48h_mm=0.0,
        cumul_pluie_72h_mm=0.0,
        vent_max_24h_kmh=10.0,
        rafales_max_24h_kmh=20.0,
        direction_vent_dominante_deg=270.0,
        direction_vent_dominante_cardinal="O",
        etp_jour_mm=2.0,
        bilan_eau_7j_mm=0.0,
        prob_pluie_max_24h_pct=0.0,
        prob_pluie_max_48h_pct=0.0,
        prob_pluie_max_72h_pct=0.0,
        tension_irrigation=False,
        prevision_t0_utc=None,
    )
    defaults.update(kwargs)
    return IndicateursVeille(**defaults)


def test_aucune_alerte() -> None:
    from apps.veille.alertes import evaluer_alertes

    ind = _ind()
    assert evaluer_alertes(ind, CONFIG_TEST) == []


def test_alerte_gel() -> None:
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_min_24h_celsius=-3.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert len(alertes) == 1
    a = alertes[0]
    assert a.type == "gel"
    assert a.niveau == "critique"
    assert a.valeur == -3.0
    assert a.seuil == -2.0
    assert "Gel" in a.titre


def test_alerte_gel_inactif() -> None:
    from apps.veille.alertes import evaluer_alertes

    config = {**CONFIG_TEST, "alertes": {**CONFIG_TEST["alertes"]}}
    config["alertes"]["gel"] = {"actif": False, "seuil_celsius": -2.0}
    ind = _ind(temperature_min_24h_celsius=-10.0)
    assert evaluer_alertes(ind, config) == []


def test_alerte_canicule() -> None:
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_max_24h_celsius=35.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert len(alertes) == 1
    assert alertes[0].type == "canicule"


def test_alerte_pluie_intense() -> None:
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(cumul_pluie_24h_mm=25.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert len(alertes) == 1
    assert alertes[0].type == "pluie_intense"
    assert alertes[0].niveau == "warning"


def test_alerte_vent_utilise_rafales() -> None:
    """Le seuil vent_fort s'évalue sur rafales, pas vent moyen."""
    from apps.veille.alertes import evaluer_alertes

    # Vent moyen sous seuil (50 km/h), rafales au-dessus (70 km/h).
    ind = _ind(vent_max_24h_kmh=50.0, rafales_max_24h_kmh=70.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert len(alertes) == 1
    assert alertes[0].type == "vent_fort"


def test_alertes_multiples_ordre_fixe() -> None:
    """Plusieurs alertes en même temps → ordre déterministe gel, canicule, pluie, vent."""
    from apps.veille.alertes import evaluer_alertes

    # Gel + pluie + vent (mais pas canicule).
    ind = _ind(
        temperature_min_24h_celsius=-3.0,
        cumul_pluie_24h_mm=25.0,
        rafales_max_24h_kmh=70.0,
    )
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert [a.type for a in alertes] == ["gel", "pluie_intense", "vent_fort"]


def test_resume_alertes_aucune() -> None:
    from apps.veille.alertes import resume_alertes

    assert resume_alertes([]) == "RAS"


def test_resume_alertes_multiple() -> None:
    from apps.veille.alertes import Alerte, resume_alertes

    a1 = Alerte("gel", "critique", "", -3.0, "°C", -2.0)
    a2 = Alerte("vent_fort", "warning", "", 70.0, "km/h", 60.0)
    assert resume_alertes([a1, a2]) == "gel + vent fort"
