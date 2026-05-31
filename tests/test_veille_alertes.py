"""Tests `apps.veille.alertes` — déclenchements seuils."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


CONFIG_TEST = {
    "alertes": {
        "gel_irrigation": {"actif": True, "seuil_celsius": 4.0},
        "gel_cultures": {"actif": True, "seuil_celsius": -2.0},
        "canicule_aeration": {"actif": True, "seuil_celsius": 25.0},
        "canicule_stress": {"actif": True, "seuil_celsius": 30.0},
        "risque_maladies": {
            "actif": True,
            "t_min_nuit_celsius": 15.0,
            "hr_seuil": 0.90,
            "heures_min": 6,
        },
        "pluie_intense": {"actif": True, "seuil_mm_24h": 20.0},
        "vent_fort": {"actif": True, "seuil_kmh": 60.0},
    }
}


def _ind(**kwargs):
    from apps.veille.indicateurs import IndicateursVeille

    defaults = dict(
        temperature_min_24h_celsius=10.0,
        temperature_max_24h_celsius=20.0,
        temperature_min_48h_celsius=10.0,
        temperature_max_48h_celsius=20.0,
        cumul_pluie_24h_mm=0.0,
        cumul_pluie_48h_mm=0.0,
        vent_max_24h_kmh=10.0,
        rafales_max_24h_kmh=20.0,
        direction_vent_dominante_deg=270.0,
        direction_vent_dominante_cardinal="O",
        etp_jour_mm=2.0,
        prob_pluie_max_24h_pct=0.0,
        prob_pluie_max_48h_pct=0.0,
        heures_humectation_24h=0,
        prevision_t0_utc=None,
    )
    defaults.update(kwargs)
    return IndicateursVeille(**defaults)


def test_aucune_alerte() -> None:
    from apps.veille.alertes import evaluer_alertes

    ind = _ind()
    assert evaluer_alertes(ind, CONFIG_TEST) == []


def test_alerte_gel_cultures_critique() -> None:
    """T° min 24 h ≤ −2 °C → gel_cultures critique."""
    from apps.veille.alertes import evaluer_alertes

    # T° basse en 24 h, mais aussi en 48 h (24 ⊂ 48), donc les 2 alertes
    # gel se déclenchent. On vérifie ici la présence et le contenu de
    # gel_cultures.
    ind = _ind(temperature_min_24h_celsius=-3.0, temperature_min_48h_celsius=-3.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    cultures = [a for a in alertes if a.type == "gel_cultures"]
    assert len(cultures) == 1
    a = cultures[0]
    assert a.niveau == "critique"
    assert a.valeur == -3.0
    assert a.seuil == -2.0
    assert "Gel" in a.titre
    assert "protéger" in a.titre.lower() or "récolter" in a.titre.lower()


def test_alerte_gel_irrigation_warning() -> None:
    """T° min 48 h ≤ 4 °C → gel_irrigation warning, sans gel_cultures si 24 h > -2 °C."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_min_24h_celsius=8.0, temperature_min_48h_celsius=3.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert len(alertes) == 1
    a = alertes[0]
    assert a.type == "gel_irrigation"
    assert a.niveau == "warning"
    assert a.valeur == 3.0
    assert a.seuil == 4.0
    assert "purger" in a.titre.lower()


def test_alerte_gel_seuil_egal_declenche() -> None:
    """Seuil inclusif : T° = seuil déclenche l'alerte."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_min_24h_celsius=-2.0, temperature_min_48h_celsius=4.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    types = [a.type for a in alertes]
    assert "gel_irrigation" in types
    assert "gel_cultures" in types


def test_alerte_gel_irrigation_inactif() -> None:
    """gel_irrigation actif=false → pas d'alerte purge même si T° basse."""
    from apps.veille.alertes import evaluer_alertes

    config = {**CONFIG_TEST, "alertes": {**CONFIG_TEST["alertes"]}}
    config["alertes"]["gel_irrigation"] = {"actif": False, "seuil_celsius": 4.0}
    ind = _ind(temperature_min_24h_celsius=8.0, temperature_min_48h_celsius=2.0)
    assert evaluer_alertes(ind, config) == []


def test_alerte_gel_cultures_inactif() -> None:
    """gel_cultures actif=false → pas d'alerte protection même si T° très basse."""
    from apps.veille.alertes import evaluer_alertes

    config = {**CONFIG_TEST, "alertes": {**CONFIG_TEST["alertes"]}}
    config["alertes"]["gel_cultures"] = {"actif": False, "seuil_celsius": -2.0}
    config["alertes"]["gel_irrigation"] = {"actif": False, "seuil_celsius": 4.0}
    ind = _ind(temperature_min_24h_celsius=-10.0, temperature_min_48h_celsius=-10.0)
    assert evaluer_alertes(ind, config) == []


def test_alerte_canicule_aeration_seule() -> None:
    """T_max 48h ≥ 25 °C mais T_max 24h < 30 °C → aération seule, warning."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_max_24h_celsius=22.0, temperature_max_48h_celsius=27.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert len(alertes) == 1
    a = alertes[0]
    assert a.type == "canicule_aeration"
    assert a.niveau == "warning"
    assert a.valeur == 27.0
    assert a.seuil == 25.0
    assert "aérer" in a.titre.lower() or "tunnels" in a.titre.lower()


def test_alerte_canicule_stress_critique() -> None:
    """T_max 24h ≥ 30 °C → stress critique. 48h ⊃ 24h donc aération aussi."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_max_24h_celsius=32.0, temperature_max_48h_celsius=32.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    types = [a.type for a in alertes]
    assert "canicule_aeration" in types
    assert "canicule_stress" in types
    stress = next(a for a in alertes if a.type == "canicule_stress")
    assert stress.niveau == "critique"
    assert stress.valeur == 32.0
    assert stress.seuil == 30.0
    assert "bassinages" in stress.titre.lower()


def test_alerte_canicule_seuil_inclusif() -> None:
    """T_max = seuil pile déclenche (≥)."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_max_24h_celsius=30.0, temperature_max_48h_celsius=25.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    types = [a.type for a in alertes]
    assert "canicule_aeration" in types
    assert "canicule_stress" in types


def test_alerte_risque_maladies_declenche() -> None:
    """T_min ≥ 15 °C ET ≥ 6 h HR ≥ 90 % → warning maladies."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_min_24h_celsius=16.0, heures_humectation_24h=8)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    types = [a.type for a in alertes]
    assert "risque_maladies" in types
    a = next(a for a in alertes if a.type == "risque_maladies")
    assert a.niveau == "warning"
    assert a.valeur == 8
    assert a.seuil == 6
    assert "maladies" in a.titre.lower()
    assert "ouvrants" in a.titre.lower()


def test_alerte_risque_maladies_pas_declenche_si_nuit_fraiche() -> None:
    """Nuit fraîche (T_min < 15) → pas d'alerte maladies même si HR élevée."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_min_24h_celsius=12.0, heures_humectation_24h=20)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert "risque_maladies" not in [a.type for a in alertes]


def test_alerte_risque_maladies_pas_declenche_si_air_sec() -> None:
    """Nuit douce mais air sec (peu d'heures HR ≥ 90 %) → pas d'alerte."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_min_24h_celsius=18.0, heures_humectation_24h=3)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert "risque_maladies" not in [a.type for a in alertes]


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
    """Plusieurs alertes en même temps → ordre déterministe :
    gel_irrigation, gel_cultures, canicule_aeration, canicule_stress,
    risque_maladies, pluie, vent."""
    from apps.veille.alertes import evaluer_alertes

    # Gel franc + pluie + vent (canicule incompatible avec gel).
    # T_min 24 h = T_min 48 h = -3 °C → les 2 alertes gel sont
    # déclenchées (24 h ⊂ 48 h, donc 48 h ≤ 4 °C aussi).
    ind = _ind(
        temperature_min_24h_celsius=-3.0,
        temperature_min_48h_celsius=-3.0,
        cumul_pluie_24h_mm=25.0,
        rafales_max_24h_kmh=70.0,
    )
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert [a.type for a in alertes] == [
        "gel_irrigation",
        "gel_cultures",
        "pluie_intense",
        "vent_fort",
    ]


def test_alertes_canicule_combo() -> None:
    """Canicule sévère + nuit douce humide → aération + stress + maladies."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(
        temperature_min_24h_celsius=17.0,
        temperature_max_24h_celsius=33.0,
        temperature_max_48h_celsius=34.0,
        heures_humectation_24h=7,
    )
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert [a.type for a in alertes] == [
        "canicule_aeration",
        "canicule_stress",
        "risque_maladies",
    ]


def test_resume_alertes_aucune() -> None:
    from apps.veille.alertes import resume_alertes

    assert resume_alertes([]) == "RAS"


def test_resume_alertes_multiple() -> None:
    from apps.veille.alertes import Alerte, resume_alertes

    a1 = Alerte("gel_cultures", "critique", "", -3.0, "°C", -2.0)
    a2 = Alerte("vent_fort", "warning", "", 70.0, "km/h", 60.0)
    assert resume_alertes([a1, a2]) == "gel cultures + vent fort"


def test_resume_alertes_canicule_maladies() -> None:
    """Le résumé conserve les sous-types canicule/maladies pour le sujet."""
    from apps.veille.alertes import Alerte, resume_alertes

    aero = Alerte("canicule_aeration", "warning", "", 28.0, "°C", 25.0)
    mal = Alerte("risque_maladies", "warning", "", 7, "h", 6)
    assert resume_alertes([aero, mal]) == "canicule aeration + risque maladies"
