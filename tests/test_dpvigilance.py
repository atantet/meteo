"""Test offline du parser DPVigilance (JSON réel capturé le 2026-06-15).

Vérifie l'extraction des tranches horodatées orages (dept 35) et le niveau max,
sur la structure exacte ``product.periods[].timelaps.domain_ids[].phenomenon_items[]``.
"""

from __future__ import annotations

import pandas as pd

from meteo_socle.sources.dpvigilance import ORAGES_ID, parser_vigilance_dp

# Échantillon fidèle à la réponse réelle (orages dept 35 : Jaune 14-16h, Vert ensuite).
_JSON = {
    "product": {
        "periods": [
            {
                "echeance": "J",
                "timelaps": {
                    "domain_ids": [
                        {
                            "domain_id": "35",
                            "max_color_id": 2,
                            "phenomenon_items": [
                                {
                                    "phenomenon_id": "3",
                                    "phenomenon_max_color_id": 2,
                                    "timelaps_items": [
                                        {
                                            "begin_time": "2026-06-15T14:00:00Z",
                                            "end_time": "2026-06-15T16:00:00Z",
                                            "color_id": 2,
                                        },
                                        {
                                            "begin_time": "2026-06-15T16:00:00Z",
                                            "end_time": "2026-06-15T22:00:00Z",
                                            "color_id": 1,
                                        },
                                    ],
                                },
                                {
                                    "phenomenon_id": "1",
                                    "phenomenon_max_color_id": 1,
                                    "timelaps_items": [],
                                },
                            ],
                        }
                    ]
                },
            },
            {
                "echeance": "J1",
                "timelaps": {
                    "domain_ids": [
                        {
                            "domain_id": "35",
                            "max_color_id": 1,
                            "phenomenon_items": [
                                {
                                    "phenomenon_id": "3",
                                    "phenomenon_max_color_id": 1,
                                    "timelaps_items": [
                                        {
                                            "begin_time": "2026-06-15T22:00:00Z",
                                            "end_time": "2026-06-16T22:00:00Z",
                                            "color_id": 1,
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                },
            },
        ]
    }
}


def test_orages_niveau_et_tranches() -> None:
    vig = parser_vigilance_dp(_JSON, "35")
    assert vig.niveau(ORAGES_ID) == 2  # Jaune (pire color_id sur J+J1)
    # tranches_orages(jaune+) → seule la fenêtre 14-16h (color 2), pas les verts.
    fen = vig.tranches_orages(niveau_min=2)
    assert len(fen) == 1
    t = fen[0]
    assert t.debut == pd.Timestamp("2026-06-15T14:00:00Z")
    assert t.fin == pd.Timestamp("2026-06-15T16:00:00Z")
    assert t.niveau == 2
    assert str(t.debut.tz) == "UTC"


def test_phenomene_absent_vert_sans_tranche() -> None:
    vig = parser_vigilance_dp(_JSON, "35")
    # Pluie-inondation (2) absente du payload → vert, aucune tranche.
    assert vig.niveau(2) == 1
    assert vig.phenomene(2).tranches == []


def test_departement_absent() -> None:
    vig = parser_vigilance_dp(_JSON, "99")
    assert vig.niveau_max_global() == 1
    assert vig.tranches_orages() == []
