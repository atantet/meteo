"""Tests de la source prévision officielle Météo-France (ADR-0014).

Couvre : le classifieur ``desc_vers_wmo`` (libellés webservice + guide officiel
MF), et le parser (conversions vers unités socle + diffusion de la proba). Les
fixtures sont en **unités natives MF** et les assertions vérifient la **plage en
unités socle** — pour attraper une conversion oubliée (cf. mémoire tests socle).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests

from meteo_socle.sources.meteofrance_officiel import (
    MeteoFranceOfficiel,
    PrevisionIndisponibleError,
    desc_vers_wmo,
)


@pytest.mark.parametrize(
    ("desc", "code"),
    [
        # Nébulosité (libellés webservice + guide).
        ("Ensoleillé", 0),
        ("Soleil", 0),
        ("Ciel clair", 0),
        ("Nuit claire", 0),
        ("Peu nuageux", 1),
        ("Éclaircies", 2),
        ("Belles Éclaircies", 2),
        ("Ciel voilé", 2),
        ("Variable ou Nuageux", 2),
        ("Très nuageux", 3),
        ("Couvert", 3),
        # Brouillard.
        ("Brumes ou Brouillards", 45),
        ("Brouillard", 45),
        ("Brouillards Givrants", 48),
        # Pluie / bruine / averses, avec intensité.
        ("Bruine", 51),
        ("Couvert, Bruines ou Pluies", 51),
        ("Pluie faible", 61),
        ("Pluie", 63),
        ("Pluie modérée", 63),
        ("Pluie forte", 65),
        ("Couvert, Pluies Modérées ou fortes", 65),
        ("Averses faibles", 80),
        ("Averses", 81),
        ("Pluies éparses / Rares averses", 80),
        # Verglas.
        ("Pluie verglaçante", 66),
        ("Verglas", 66),
        # Neige.
        ("Couvert, Neige Faible", 71),
        ("Quelques flocons", 71),
        ("Neige forte", 75),
        ("Couvert Neige Modérée ou Forte", 75),
        ("Variable, Averses de Neige", 85),
        ("Pluie et neige", 66),
        # Orage (priorité) + grêle.
        ("Orages", 95),
        ("Risque d'orages", 95),
        ("Averses orageuses", 95),
        ("Orage avec grêle", 96),
        ("Averses de grêle", 96),
    ],
)
def test_desc_vers_wmo(desc: str, code: int) -> None:
    assert desc_vers_wmo(desc) == code


def test_desc_vers_wmo_inconnu_ou_vide() -> None:
    assert desc_vers_wmo("") is None
    assert desc_vers_wmo("Phénomène martien") is None


def _payload_synthetique() -> dict:
    """Mini-payload webservice MF (unités natives : °C, %, m/s, mm)."""
    h0 = 1_780_700_400  # epoch s, heure ronde UTC
    return {
        "updated_on": h0 - 1800,
        "position": {"name": "Sains", "lat": 48.37, "lon": -1.57, "alti": 100},
        "forecast": [
            {
                "dt": h0,
                "T": {"value": 12.5},
                "humidity": 90,
                "wind": {"speed": 6, "gust": 12, "direction": 165},
                "rain": {"1h": 0.0},
                "clouds": 70,
                "weather": {"icon": "p3bisj", "desc": "Très nuageux"},
            },
            {
                "dt": h0 + 3600,
                "T": {"value": 14.0},
                "humidity": 80,
                "wind": {"speed": 5, "gust": 10, "direction": -1},  # vent variable
                "rain": {"1h": 1.2},
                "clouds": 100,
                "weather": {"icon": "p?", "desc": "Pluie faible"},
            },
        ],
        "probability_forecast": [
            {"dt": h0, "rain": {"3h": 40, "6h": None}, "snow": {}, "freezing": 0},
        ],
    }


def test_parser_unites_socle() -> None:
    prev = MeteoFranceOfficiel.parser(_payload_synthetique())
    df = prev.df

    # Index UTC tz-aware, ordonné.
    assert str(df.index.tz) == "UTC"
    assert df.index.is_monotonic_increasing

    # Température : °C → K (plage physique stricte).
    assert (df["temperature_2m"] > 250).all() and (df["temperature_2m"] < 320).all()
    assert df["temperature_2m"].iloc[0] == pytest.approx(12.5 + 273.15)

    # HR et nébulosité : % → fraction [0, 1].
    assert (df["humidite_relative"].between(0, 1)).all()
    assert (df["cloud_cover"].between(0, 1)).all()
    assert df["humidite_relative"].iloc[0] == pytest.approx(0.90)

    # Vent : m/s, AUCUNE conversion (vérifié vs Open-Meteo).
    assert df["vitesse_vent_10m"].iloc[0] == 6
    assert df["rafales_vent_10m"].iloc[0] == 12

    # Direction variable (-1) → NaN.
    assert pd.isna(df["direction_vent_deg"].iloc[1])

    # Pluie en mm, telle quelle.
    assert df["precipitation"].iloc[1] == pytest.approx(1.2)

    # Code temps dérivé du desc MF.
    assert df["weather_code"].iloc[0] == 3  # Très nuageux
    assert df["weather_code"].iloc[1] == 61  # Pluie faible

    # Proba diffusée sur la fenêtre 3 h.
    assert df["probabilite_pluie_pct"].iloc[0] == pytest.approx(40.0)
    assert df["probabilite_pluie_pct"].iloc[1] == pytest.approx(40.0)

    # Provenance.
    assert str(prev.updated_on.tz) == "UTC"
    assert prev.position["name"] == "Sains"


def test_parser_payload_vide_leve() -> None:
    with pytest.raises(PrevisionIndisponibleError):
        MeteoFranceOfficiel.parser({"forecast": []})


def test_obtenir_prevision_retry_sur_connect_timeout(monkeypatch) -> None:
    """ConnectTimeout transitoire (webservice MF injoignable) : on réessaie.

    Régression de l'échec CI 2026-06-06 : le webservice MF time out par
    intermittence depuis les runners ; la première tentative échoue au niveau
    connexion, la suivante réussit.
    """
    from meteo_socle.sources import _http_retry

    monkeypatch.setattr(_http_retry.time, "sleep", lambda _: None)

    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.json.return_value = {
        "forecast": [{"dt": 1_733_000_400, "T": {"value": 12.0}, "weather": {"desc": "Couvert"}}],
        "position": {"name": "Sains"},
    }
    session = MagicMock()
    session.get.side_effect = [requests.ConnectTimeout("timed out"), resp_ok]

    prevision = MeteoFranceOfficiel(session=session).obtenir_prevision(48.543648, -1.611515)

    assert session.get.call_count == 2
    assert prevision.position["name"] == "Sains"


def test_obtenir_prevision_connect_timeout_persistant_leve(monkeypatch) -> None:
    """ConnectTimeout sur toutes les tentatives → PrevisionIndisponibleError propre.

    Le webservice injoignable ne doit pas remonter un traceback brut (exit 1 en
    CI) mais l'erreur métier attendue.
    """
    from meteo_socle.sources import _http_retry

    monkeypatch.setattr(_http_retry.time, "sleep", lambda _: None)

    session = MagicMock()
    session.get.side_effect = requests.ConnectTimeout("timed out")

    with pytest.raises(PrevisionIndisponibleError):
        MeteoFranceOfficiel(session=session).obtenir_prevision(48.543648, -1.611515)
    assert session.get.call_count == 4  # _MAX_TENTATIVES
