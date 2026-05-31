"""Tests offline du parser Vigilance Météo-France.

Couvre :
- Parsing nominal d'un JSON DPVigilance avec un département en jaune.
- Cas "tout vert" (aucun phénomène déclenché).
- Cas département absent (fallback tous verts).
- Robustesse face à un JSON mal formé.
- Filtrage sur les phénomènes pertinents (pas de Crues/Avalanches/Submersion).
- Désactivation gracieuse quand ENV absente (recuperer_vigilance retourne None).
"""

from __future__ import annotations

import os

import pytest

from meteo_socle.sources.meteofrance_vigilance import (
    ENV_APP_ID,
    PHENOMENES_PERTINENTS,
    parser_vigilance,
    recuperer_vigilance,
)


def _payload_vigilance(
    departement: str = "35",
    phen_j: dict[str, int] | None = None,
    phen_j1: dict[str, int] | None = None,
) -> dict:
    """Fabrique un payload DPVigilance minimal pour les tests."""
    phen_j = phen_j or {}
    phen_j1 = phen_j1 or {}

    def items(d: dict[str, int]) -> list[dict]:
        return [
            {"phenomenon_id": pid, "phenomenon_max_color_id": niveau} for pid, niveau in d.items()
        ]

    return {
        "product": {
            "update_time": "2026-05-31T16:00:00Z",
            "periods": [
                {
                    "echeance": "J",
                    "timelaps": {
                        "domain_ids": [
                            {"domain_id": departement, "phenomenon_items": items(phen_j)},
                        ]
                    },
                },
                {
                    "echeance": "J1",
                    "timelaps": {
                        "domain_ids": [
                            {"domain_id": departement, "phenomenon_items": items(phen_j1)},
                        ]
                    },
                },
            ],
        }
    }


def test_parser_vigilance_tout_vert() -> None:
    """Sans phénomène déclenché, tous les niveaux sont à 1 (vert)."""
    payload = _payload_vigilance(departement="35")
    res = parser_vigilance(payload, departement="35")
    assert res is not None
    assert res.departement == "35"
    assert res.niveau_max_global == 1
    assert all(p.niveau_j == 1 and p.niveau_j1 == 1 for p in res.phenomenes)


def test_parser_vigilance_orage_jaune_j_orange_j1() -> None:
    """Un phénomène jaune J et orange J+1 → niveau_max = 3 (orange)."""
    payload = _payload_vigilance(
        departement="35",
        phen_j={"3": 2},  # Orages jaune J
        phen_j1={"3": 3},  # Orages orange J+1
    )
    res = parser_vigilance(payload, departement="35")
    assert res is not None
    orages = next(p for p in res.phenomenes if p.code == 3)
    assert orages.niveau_j == 2
    assert orages.niveau_j1 == 3
    assert orages.niveau_max == 3
    assert res.niveau_max_global == 3


def test_parser_vigilance_filtre_phenomenes_pertinents() -> None:
    """Seuls les phénomènes pertinents Pleine-Fougères sont exposés."""
    payload = _payload_vigilance(
        departement="35",
        phen_j={
            "3": 2,
            "4": 4,
            "8": 4,
            "9": 4,
        },  # Orages jaune + crues/avalanches/submersion rouges
    )
    res = parser_vigilance(payload, departement="35")
    assert res is not None
    codes = {p.code for p in res.phenomenes}
    assert codes == set(PHENOMENES_PERTINENTS)
    # Le rouge sur avalanches/crues/submersion doit être ignoré (niveau max
    # global lu uniquement sur les phénomènes retenus).
    assert res.niveau_max_global == 2  # = jaune des orages, pas le rouge filtré


def test_parser_vigilance_departement_absent() -> None:
    """Département non trouvé dans le payload → fallback tous verts."""
    payload = _payload_vigilance(
        departement="13",  # Bouches-du-Rhône, pas 35
        phen_j={"6": 4},  # Canicule rouge dans le 13, ne doit pas remonter au 35
    )
    res = parser_vigilance(payload, departement="35")
    assert res is not None
    assert res.niveau_max_global == 1


def test_parser_vigilance_payload_malforme() -> None:
    """Payload vide ou incomplet → ne crash pas, retourne tous verts."""
    res = parser_vigilance({}, departement="35")
    assert res is not None
    assert res.niveau_max_global == 1

    res = parser_vigilance({"product": {"periods": []}}, departement="35")
    assert res is not None
    assert res.niveau_max_global == 1


def test_parser_vigilance_niveau_invalide_ignore() -> None:
    """Un niveau hors plage [1,4] est ignoré silencieusement."""
    payload = _payload_vigilance(
        departement="35",
        phen_j={"3": 7},  # Niveau hors plage
    )
    res = parser_vigilance(payload, departement="35")
    assert res is not None
    orages = next(p for p in res.phenomenes if p.code == 3)
    assert orages.niveau_j == 1  # fallback vert


def test_recuperer_vigilance_sans_cle_retourne_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans clé API, recuperer_vigilance retourne None sans appel réseau."""
    monkeypatch.delenv(ENV_APP_ID, raising=False)
    assert os.environ.get(ENV_APP_ID) is None
    res = recuperer_vigilance(departement="35")
    assert res is None
