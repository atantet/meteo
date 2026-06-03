"""Tests `apps.veille.alertes` — déclenchements seuils."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


CONFIG_TEST = {
    "alertes": {
        "gel": {"actif": True, "seuil_celsius": 4.0},
        "canicule_aeration": {"actif": True, "seuil_celsius": 25.0},
        "canicule_stress": {"actif": True, "seuil_celsius": 30.0},
        "risque_maladies": {"actif": True, "t_min_nuit_celsius": 15.0},
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
        temperature_min_nuit_prochaine_celsius=10.0,
        cumul_pluie_24h_mm=0.0,
        cumul_pluie_48h_mm=0.0,
        vent_max_24h_kmh=10.0,
        rafales_max_24h_kmh=20.0,
        direction_vent_dominante_deg=270.0,
        direction_vent_dominante_cardinal="O",
        etp_jour_mm=2.0,
        prob_pluie_max_24h_pct=0.0,
        prob_pluie_max_48h_pct=0.0,
        prevision_t0_utc=None,
    )
    defaults.update(kwargs)
    return IndicateursVeille(**defaults)


def test_aucune_alerte() -> None:
    from apps.veille.alertes import evaluer_alertes

    ind = _ind()
    assert evaluer_alertes(ind, CONFIG_TEST) == []


def test_alerte_gel_declenche() -> None:
    """T° min 48 h ≤ 4 °C → alerte unique « gel » (purge + voilage), warning."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_min_24h_celsius=8.0, temperature_min_48h_celsius=3.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert len(alertes) == 1
    a = alertes[0]
    assert a.type == "gel"
    assert a.niveau == "warning"
    assert a.valeur == 3.0
    assert a.seuil == 4.0
    assert "purger" in a.titre.lower()
    assert "voiler" in a.titre.lower()


def test_alerte_gel_une_seule_meme_si_tres_froid() -> None:
    """Plus de distinction irrigation/cultures : une seule alerte gel, même à −3 °C."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_min_24h_celsius=-3.0, temperature_min_48h_celsius=-3.0)
    gels = [a for a in evaluer_alertes(ind, CONFIG_TEST) if a.type == "gel"]
    assert len(gels) == 1


def test_alerte_gel_seuil_egal_declenche() -> None:
    """Seuil inclusif : T° min 48 h = seuil déclenche l'alerte."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_min_48h_celsius=4.0)
    assert "gel" in [a.type for a in evaluer_alertes(ind, CONFIG_TEST)]


def test_alerte_gel_inactif() -> None:
    """gel actif=false → pas d'alerte même si T° très basse."""
    from apps.veille.alertes import evaluer_alertes

    config = {**CONFIG_TEST, "alertes": {**CONFIG_TEST["alertes"]}}
    config["alertes"]["gel"] = {"actif": False, "seuil_celsius": 4.0}
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
    """T° min nuit à venir ≥ 15 °C → warning maladies (condition température seule)."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_min_nuit_prochaine_celsius=16.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    types = [a.type for a in alertes]
    assert "risque_maladies" in types
    a = next(a for a in alertes if a.type == "risque_maladies")
    assert a.niveau == "warning"
    assert a.valeur == 16.0
    assert a.seuil == 15.0
    assert a.unite == "°C"
    assert "maladies" in a.titre.lower()
    assert "ouvrants" in a.titre.lower()


def test_alerte_risque_maladies_utilise_nuit_pas_24h() -> None:
    """Le déclenchement suit la nuit à venir, pas le min 24 h global."""
    from apps.veille.alertes import evaluer_alertes

    # Min 24 h froid (gel passé) mais nuit À VENIR douce → maladies.
    ind = _ind(
        temperature_min_24h_celsius=2.0,
        temperature_min_nuit_prochaine_celsius=16.0,
    )
    assert "risque_maladies" in [a.type for a in evaluer_alertes(ind, CONFIG_TEST)]


def test_alerte_risque_maladies_pas_declenche_si_nuit_fraiche() -> None:
    """Nuit à venir fraîche (< 15 °C) → pas d'alerte maladies."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(temperature_min_nuit_prochaine_celsius=12.0)
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert "risque_maladies" not in [a.type for a in alertes]


def test_alerte_risque_maladies_independant_humidite() -> None:
    """Plus de critère HR : une nuit douce suffit, quelle que soit l'humidité."""
    from apps.veille.alertes import evaluer_alertes

    # Aucune info d'humidité dans les indicateurs → l'alerte se déclenche
    # quand même (condition température seule).
    ind = _ind(temperature_min_nuit_prochaine_celsius=18.0)
    assert "risque_maladies" in [a.type for a in evaluer_alertes(ind, CONFIG_TEST)]


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
    gel, canicule_aeration, canicule_stress, risque_maladies, pluie, vent."""
    from apps.veille.alertes import evaluer_alertes

    # Gel + pluie + vent (canicule incompatible avec gel).
    ind = _ind(
        temperature_min_48h_celsius=-3.0,
        cumul_pluie_24h_mm=25.0,
        rafales_max_24h_kmh=70.0,
    )
    alertes = evaluer_alertes(ind, CONFIG_TEST)
    assert [a.type for a in alertes] == [
        "gel",
        "pluie_intense",
        "vent_fort",
    ]


def test_alertes_canicule_combo() -> None:
    """Canicule sévère + nuit douce → aération + stress + maladies."""
    from apps.veille.alertes import evaluer_alertes

    ind = _ind(
        temperature_min_nuit_prochaine_celsius=17.0,
        temperature_max_24h_celsius=33.0,
        temperature_max_48h_celsius=34.0,
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

    a1 = Alerte("gel", "warning", "", -3.0, "°C", 4.0)
    a2 = Alerte("vent_fort", "warning", "", 70.0, "km/h", 60.0)
    assert resume_alertes([a1, a2]) == "gel + vent fort"


def test_resume_alertes_canicule_maladies() -> None:
    """Le résumé conserve les sous-types canicule/maladies pour le sujet."""
    from apps.veille.alertes import Alerte, resume_alertes

    aero = Alerte("canicule_aeration", "warning", "", 28.0, "°C", 25.0)
    mal = Alerte("risque_maladies", "warning", "", 7, "h", 6)
    assert resume_alertes([aero, mal]) == "canicule aeration + risque maladies"
