"""Tests `meteo_socle.indices.pepiniere` (cf. ADR-0009)."""

from __future__ import annotations

from datetime import date

import pytest

from meteo_socle.indices.pepiniere import (
    calendrier_semis,
    cultures_disponibles,
    date_semis_recommandee,
    duree_elevage_jours,
    est_sensible_gel,
)


def test_cultures_disponibles_inclut_principales_maraichage() -> None:
    cultures = cultures_disponibles()
    for c in ("Tomate", "Aubergine", "Poivron", "Courgette", "Salade"):
        # Salade référencée comme "Laitue (Salade)".
        assert any(c.lower() in x.lower() for x in cultures), f"{c} attendue"


def test_duree_elevage_tomate_environ_50_jours() -> None:
    # Valeur médiane praticiens — fenêtre 40-60 raisonnable.
    d = duree_elevage_jours("Tomate")
    assert 40 <= d <= 60


def test_culture_inconnue_raise_keyerror() -> None:
    with pytest.raises(KeyError):
        duree_elevage_jours("Banane")


def test_sensibilite_gel_tomate_vraie() -> None:
    assert est_sensible_gel("Tomate")


def test_sensibilite_gel_chou_fausse() -> None:
    assert not est_sensible_gel("Chou pommé")


def test_date_semis_recommandee_tomate_planter_15_mai() -> None:
    cible = date(2026, 5, 15)
    semis = date_semis_recommandee("Tomate", cible, marge_securite_j=7)
    # 50 j élevage + 7 j marge = 57 j avant le 15 mai → 19 mars.
    delta = (cible - semis).days
    assert delta == duree_elevage_jours("Tomate") + 7


def test_semis_direct_renvoie_date_cible() -> None:
    """Semis direct (carotte) : date_semis = date_plantation."""
    cible = date(2026, 4, 1)
    assert date_semis_recommandee("Carotte", cible) == cible


def test_calendrier_semis_defaut_filtre_sensibles_gel() -> None:
    cal = calendrier_semis(date(2026, 5, 15))
    assert all(entree["sensible_gel"] for entree in cal)
    # Tomate, Aubergine, Poivron, Courgette… devraient figurer.
    cultures = {e["culture"] for e in cal}
    assert {"Tomate", "Aubergine", "Courgette"}.issubset(cultures)


def test_calendrier_semis_dates_anterieures_a_la_cible() -> None:
    cible = date(2026, 5, 15)
    cal = calendrier_semis(cible)
    for entree in cal:
        assert entree["date_semis"] <= cible
        assert entree["date_plantation"] == cible


def test_calendrier_semis_culture_specifiee_n_filtre_pas() -> None:
    """Si l'utilisateur passe Carotte explicitement, elle est incluse."""
    cal = calendrier_semis(date(2026, 5, 15), cultures=["Carotte", "Tomate"])
    cultures = {e["culture"] for e in cal}
    assert cultures == {"Carotte", "Tomate"}
