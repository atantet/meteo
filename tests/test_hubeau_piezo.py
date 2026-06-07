"""Tests `meteo_socle.sources.hubeau_piezo` (parsing + position saisonnière)."""

from __future__ import annotations

import pandas as pd

from meteo_socle.sources.hubeau_piezo import parser_etat_nappe


def _mesures() -> list[dict]:
    # Juins historiques (un point/an) + un mois de mai et le dernier point juin.
    return [
        {"date_mesure": "2020-06-01", "niveau_nappe_eau": 76.0, "profondeur_nappe": 11.0},
        {"date_mesure": "2021-06-01", "niveau_nappe_eau": 77.0, "profondeur_nappe": 10.0},
        {"date_mesure": "2022-06-01", "niveau_nappe_eau": 78.0, "profondeur_nappe": 9.0},
        {"date_mesure": "2023-06-01", "niveau_nappe_eau": 79.0, "profondeur_nappe": 8.0},
        {"date_mesure": "2024-05-16", "niveau_nappe_eau": 77.9, "profondeur_nappe": 9.1},
        {"date_mesure": "2024-06-15", "niveau_nappe_eau": 77.5, "profondeur_nappe": 9.5},
    ]


def test_parse_position_saisonniere() -> None:
    etat = parser_etat_nappe(_mesures(), now=pd.Timestamp("2024-06-20"))
    assert etat is not None
    assert etat.mois == 6
    assert etat.niveau_ngf == 77.5
    assert etat.age_jours == 5
    # Juins = [76, 77, 78, 79, 77.5] ; rang de 77.5 = 2 → 40e percentile.
    assert etat.percentile_saison == 40
    assert etat.classe_saison == "normal"
    assert etat.mediane_saison_ngf == 77.5
    assert etat.min_saison_ngf == 76.0
    assert etat.max_saison_ngf == 79.0
    assert etat.n_annees_saison == 5


def test_tendance_30j() -> None:
    etat = parser_etat_nappe(_mesures(), now=pd.Timestamp("2024-06-20"))
    assert etat is not None
    # 77.5 (15/06) vs 77.9 (16/05) ≈ -0.4 m.
    assert etat.delta_30j_m == -0.4


def test_plus_bas_historique() -> None:
    etat = parser_etat_nappe(_mesures(), now=pd.Timestamp("2024-06-20"))
    assert etat is not None
    assert etat.plus_bas_ngf == 76.0
    assert etat.plus_bas_date == pd.Timestamp("2020-06-01")


def test_classe_bas_et_haut() -> None:
    # Dernier point très bas (sous tous les juins) → percentile 0 → bas.
    bas = parser_etat_nappe(
        [
            {"date_mesure": "2021-06-01", "niveau_nappe_eau": 78.0},
            {"date_mesure": "2022-06-01", "niveau_nappe_eau": 79.0},
            {"date_mesure": "2024-06-01", "niveau_nappe_eau": 75.0},
        ],
        now=pd.Timestamp("2024-06-02"),
    )
    assert bas is not None and bas.classe_saison == "bas"


def test_vide_et_invalide() -> None:
    assert parser_etat_nappe([]) is None
    assert parser_etat_nappe([{"foo": "bar"}]) is None
