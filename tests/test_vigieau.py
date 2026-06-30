"""Tests `meteo_socle.sources.vigieau` (parsing situation restrictions)."""

from __future__ import annotations

from meteo_socle.sources.vigieau import NIVEAU_AUCUNE, parser_restrictions

_USAGE_IRRIGATION_CULTURES_SPECIALES = {
    "nom": "Irrigation agricole des cultures spéciales",
    "thematique": "Irriguer",
    "description": "Interdit de 11h à 18h sauf si irrigation au goutte à goutte.",
    "concerneExploitation": True,
}
_USAGE_IRRIGATION_AUTRES = {
    "nom": "Irrigation agricole des autres types de cultures",
    "thematique": "Irriguer",
    "description": "Interdiction de 10h à 20h.",
    "concerneExploitation": True,
}
_USAGE_NETTOYAGE = {
    "nom": "Nettoyage de la voirie",
    "thematique": "Nettoyer",
    "description": "Réduction volontaire.",
    "concerneExploitation": True,
}
_USAGE_PARTICULIER = {
    "nom": "Potagers bac et jardin",
    "thematique": "Arroser",
    "description": "Interdiction de 10h à 20h.",
    "concerneExploitation": False,
}


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
        {"type": "SOU", "niveauGravite": "alerte", "nom": "Nappe de socle", "usages": []},
        {"type": "SUP", "niveauGravite": "vigilance", "nom": "Le Couesnon", "usages": []},
    ]
    r = parser_restrictions(data)
    assert r is not None
    assert len(r.zones) == 2
    assert r.niveau_max == "alerte"
    assert r.niveau_souterrain == "alerte"


def test_normalisation_alerte_renforcee() -> None:
    r = parser_restrictions(
        [{"type": "SOU", "niveauGravite": "Alerte renforcée", "nom": "X", "usages": []}]
    )
    assert r is not None
    assert r.niveau_max == "alerte_renforcee"
    assert r.niveau_max_label == "Alerte renforcée"


def test_souterrain_aucune_si_que_superficiel() -> None:
    r = parser_restrictions([{"type": "SUP", "niveauGravite": "crise", "nom": "X", "usages": []}])
    assert r is not None
    assert r.niveau_max == "crise"
    assert r.niveau_souterrain == NIVEAU_AUCUNE


def test_dict_erreur_non_404() -> None:
    assert parser_restrictions({"statusCode": 500}) is None


def test_usages_irrigation_filtres() -> None:
    """Seuls les usages Irriguer + concerneExploitation=True sont extraits."""
    data = [
        {
            "type": "SOU",
            "niveauGravite": "alerte",
            "nom": "Nappe de socle",
            "usages": [
                _USAGE_IRRIGATION_CULTURES_SPECIALES,
                _USAGE_IRRIGATION_AUTRES,
                _USAGE_NETTOYAGE,  # thématique ≠ Irriguer → exclu
                _USAGE_PARTICULIER,  # concerneExploitation=False → exclu
            ],
        }
    ]
    r = parser_restrictions(data)
    assert r is not None
    zone = r.zones[0]
    assert len(zone.usages_irrigation) == 2
    noms = [u.nom for u in zone.usages_irrigation]
    assert "Irrigation agricole des cultures spéciales" in noms
    assert "Irrigation agricole des autres types de cultures" in noms
    assert "Nettoyage de la voirie" not in noms


def test_usages_absent_ok() -> None:
    """Zone sans champ usages → liste vide, pas d'erreur."""
    r = parser_restrictions([{"type": "SOU", "niveauGravite": "alerte", "nom": "X"}])
    assert r is not None
    assert r.zones[0].usages_irrigation == ()
