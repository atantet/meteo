"""Tests `meteo_socle.sources.vigieau` (parsing situation restrictions)."""

from __future__ import annotations

from meteo_socle.sources.vigieau import NIVEAU_AUCUNE, parser_restrictions


def test_aucune_restriction_liste_vide() -> None:
    r = parser_restrictions([])
    assert r is not None
    assert r.zones == []
    assert r.niveau_max == NIVEAU_AUCUNE
    assert r.niveau_max_label == "Aucune restriction en vigueur"


def test_aucune_restriction_404() -> None:
    # VigiEau renvoie un dict 404 quand aucune zone n'est en vigueur.
    r = parser_restrictions({"statusCode": 404, "message": "Aucune zone"})
    assert r is not None
    assert r.niveau_max == NIVEAU_AUCUNE


def test_zones_niveau_max_et_souterrain() -> None:
    data = [
        {"type": "SOU", "niveauGravite": "alerte", "nom": "Nappe de socle"},
        {"type": "SUP", "niveauGravite": "vigilance", "nom": "Le Couesnon"},
    ]
    r = parser_restrictions(data)
    assert r is not None
    assert len(r.zones) == 2
    assert r.niveau_max == "alerte"
    assert r.niveau_souterrain == "alerte"


def test_normalisation_alerte_renforcee() -> None:
    r = parser_restrictions([{"type": "SOU", "niveauGravite": "Alerte renforcée", "nom": "X"}])
    assert r is not None
    assert r.niveau_max == "alerte_renforcee"
    assert r.niveau_max_label == "Alerte renforcée"


def test_souterrain_aucune_si_que_superficiel() -> None:
    r = parser_restrictions([{"type": "SUP", "niveauGravite": "crise", "nom": "X"}])
    assert r is not None
    assert r.niveau_max == "crise"
    assert r.niveau_souterrain == NIVEAU_AUCUNE


def test_dict_erreur_non_404() -> None:
    assert parser_restrictions({"statusCode": 500}) is None
