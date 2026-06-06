"""Tests offline du parser Vigilance Météo-France (webservice, ADR-0014).

Couvre : parsing nominal (``phenomenons_max_colors``), cas tout vert, filtrage
des phénomènes pertinents, robustesse JSON, niveau hors plage, et dégradation
gracieuse sur erreur réseau.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import requests

from meteo_socle.sources.meteofrance_vigilance import (
    PHENOMENES_PERTINENTS,
    parser_vigilance,
    recuperer_vigilance,
)


def _payload(
    phen: dict[str, int] | None = None,
    update_time: int = 1_780_718_405,
    end_validity_time: int = 1_780_783_200,
) -> dict:
    """Payload ``currentphenomenons`` minimal du webservice MF."""
    phen = phen or {}
    return {
        "update_time": update_time,
        "end_validity_time": end_validity_time,
        "domain_id": "35",
        "phenomenons_max_colors": [
            {"phenomenon_id": pid, "phenomenon_max_color_id": niv} for pid, niv in phen.items()
        ],
    }


def test_parser_tout_vert() -> None:
    res = parser_vigilance(_payload(), departement="35")
    assert res is not None
    assert res.departement == "35"
    assert res.niveau_max_global == 1
    assert all(p.niveau == 1 for p in res.phenomenes)
    # Horodatages parsés en UTC.
    assert str(res.update_time.tz) == "UTC"
    assert res.fin_validite is not None and str(res.fin_validite.tz) == "UTC"


def test_parser_orage_jaune() -> None:
    res = parser_vigilance(_payload(phen={"3": 2}), departement="35")
    assert res is not None
    orages = next(p for p in res.phenomenes if p.code == 3)
    assert orages.niveau == 2
    assert res.niveau_max_global == 2


def test_parser_filtre_phenomenes_pertinents() -> None:
    # Orages jaune + crues/avalanches/submersion rouges (hors périmètre).
    res = parser_vigilance(_payload(phen={"3": 2, "4": 4, "8": 4, "9": 4}), departement="35")
    assert res is not None
    assert {p.code for p in res.phenomenes} == set(PHENOMENES_PERTINENTS)
    # Le rouge des phénomènes filtrés ne remonte pas.
    assert res.niveau_max_global == 2


def test_parser_payload_malforme() -> None:
    for data in ({}, {"phenomenons_max_colors": []}):
        res = parser_vigilance(data, departement="35")
        assert res is not None
        assert res.niveau_max_global == 1


def test_parser_niveau_invalide_ignore() -> None:
    res = parser_vigilance(_payload(phen={"3": 7}), departement="35")
    assert res is not None
    orages = next(p for p in res.phenomenes if p.code == 3)
    assert orages.niveau == 1  # hors plage → fallback vert


def test_recuperer_vigilance_erreur_reseau_none() -> None:
    """Erreur réseau → None (bloc Vigilance omis, dégradation gracieuse)."""
    sess = MagicMock()
    sess.get.side_effect = requests.ConnectionError("down")
    assert recuperer_vigilance(departement="35", session=sess) is None


def test_recuperer_vigilance_nominal_via_mock() -> None:
    """Pipeline fetch → parse via session mockée (offline)."""
    resp = MagicMock()
    resp.json.return_value = _payload(phen={"3": 3})
    resp.raise_for_status = MagicMock()
    sess = MagicMock()
    sess.get.return_value = resp
    res = recuperer_vigilance(departement="35", session=sess)
    assert res is not None
    assert next(p for p in res.phenomenes if p.code == 3).niveau == 3
    assert isinstance(res.update_time, pd.Timestamp)
