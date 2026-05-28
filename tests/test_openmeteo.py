"""Tests unitaires `meteo_socle.sources.openmeteo` (mock HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_payload() -> dict:
    """Réponse Open-Meteo synthétique pour 3 h de prévision."""
    return {
        "latitude": 48.5420,
        "longitude": -1.6155,
        "elevation": 30.0,
        "timezone": "UTC",
        "hourly_units": {
            "time": "iso8601",
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "precipitation": "mm",
            "wind_speed_10m": "m/s",
            "wind_gusts_10m": "m/s",
            "shortwave_radiation": "W/m²",
            "et0_fao_evapotranspiration": "mm",
            "cloud_cover": "%",
        },
        "hourly": {
            "time": [
                "2024-06-15T00:00",
                "2024-06-15T01:00",
                "2024-06-15T02:00",
            ],
            "temperature_2m": [10.5, 10.0, 9.5],
            "relative_humidity_2m": [80.0, 82.0, 85.0],
            "precipitation": [0.0, 0.1, 0.5],
            "wind_speed_10m": [5.0, 4.5, 4.0],
            "wind_gusts_10m": [9.0, 8.0, 7.5],
            "shortwave_radiation": [0.0, 0.0, 0.0],
            "et0_fao_evapotranspiration": [0.03, 0.02, 0.01],
            "cloud_cover": [50.0, 60.0, 70.0],
        },
    }


def test_obtenir_prevision_conversions_unites(fake_payload: dict) -> None:
    """Vérifie le parsing JSON et les conversions vers les unités socle."""
    from meteo_socle.sources.openmeteo import OpenMeteoForecast

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = fake_payload
    mock_response.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_response

    client = OpenMeteoForecast(session=mock_session)
    df = client.obtenir_prevision(latitude=48.5420, longitude=-1.6155, horizon_jours=1)

    # Index : tz-aware UTC.
    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"
    assert len(df) == 3

    # T : °C → K (10.5 + 273.15 = 283.65).
    assert df["temperature_2m"].iloc[0] == pytest.approx(283.65)
    # HR : % → fraction (80 / 100 = 0.8).
    assert df["humidite_relative"].iloc[0] == pytest.approx(0.80)
    # cloud_cover : % → fraction.
    assert df["cloud_cover"].iloc[0] == pytest.approx(0.50)
    # Rayonnement : W/m² → J/m²/h (× 3600). À 0 W/m² la nuit, reste 0.
    assert df["rayonnement_global"].iloc[0] == pytest.approx(0.0)
    # Vent en m/s : identité.
    assert df["vitesse_vent_10m"].iloc[0] == pytest.approx(5.0)
    # Rafales en m/s : identité.
    assert df["rafales_vent_10m"].iloc[0] == pytest.approx(9.0)
    # Pluie en mm : identité.
    assert df["precipitation"].iloc[0] == pytest.approx(0.0)
    # ETP Open-Meteo en mm/h : identité (renommée).
    assert df["etp_open_meteo"].iloc[0] == pytest.approx(0.03)


def test_obtenir_prevision_rayonnement_jour(fake_payload: dict) -> None:
    """Conversion W/m² → J/m²/h sur valeur de jour."""
    from meteo_socle.sources.openmeteo import OpenMeteoForecast

    # Modifie le payload pour avoir une valeur de jour.
    fake_payload["hourly"]["shortwave_radiation"] = [500.0, 600.0, 700.0]

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = fake_payload
    mock_session.get.return_value = mock_response

    client = OpenMeteoForecast(session=mock_session)
    df = client.obtenir_prevision(latitude=0, longitude=0, horizon_jours=1)

    # 500 W/m² × 3600 s = 1 800 000 J/m²/h = 1.8 MJ/m²/h
    assert df["rayonnement_global"].iloc[0] == pytest.approx(1_800_000.0)
    assert df["rayonnement_global"].iloc[2] == pytest.approx(2_520_000.0)


def test_obtenir_prevision_query_params(fake_payload: dict) -> None:
    """Vérifie les paramètres HTTP envoyés à Open-Meteo."""
    from meteo_socle.sources.openmeteo import OpenMeteoForecast

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = fake_payload
    mock_session.get.return_value = mock_response

    client = OpenMeteoForecast(modele="meteofrance_arome_france_hd", session=mock_session)
    client.obtenir_prevision(latitude=48.5, longitude=-1.6, horizon_jours=3)

    args, kwargs = mock_session.get.call_args
    assert args[0] == "https://api.open-meteo.com/v1/forecast"
    params = kwargs["params"]
    assert params["latitude"] == "48.5"
    assert params["longitude"] == "-1.6"
    assert params["forecast_days"] == "3"
    assert params["models"] == "meteofrance_arome_france_hd"
    assert params["timezone"] == "UTC"
    assert params["temperature_unit"] == "celsius"
    assert params["wind_speed_unit"] == "ms"
    assert params["precipitation_unit"] == "mm"
    # Liste des variables horaires demandées.
    assert "temperature_2m" in params["hourly"]
    assert "et0_fao_evapotranspiration" in params["hourly"]


def test_obtenir_prevision_http_error(fake_payload: dict) -> None:
    """En cas de réponse non-200, raise_for_status doit propager."""
    import requests

    from meteo_socle.sources.openmeteo import OpenMeteoForecast

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("500")
    mock_session.get.return_value = mock_response

    client = OpenMeteoForecast(session=mock_session)
    with pytest.raises(requests.HTTPError):
        client.obtenir_prevision(latitude=0, longitude=0, horizon_jours=1)


def test_obtenir_prevision_colonnes_seulement_demandees(fake_payload: dict) -> None:
    """Si on ne demande qu'un sous-ensemble de variables, seules celles-ci sortent."""
    from meteo_socle.sources.openmeteo import OpenMeteoForecast

    # Payload restreint.
    restricted = {
        "hourly": {
            "time": ["2024-06-15T00:00"],
            "temperature_2m": [10.5],
            "precipitation": [0.0],
        }
    }
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = restricted
    mock_session.get.return_value = mock_response

    client = OpenMeteoForecast(session=mock_session)
    df = client.obtenir_prevision(
        latitude=0,
        longitude=0,
        horizon_jours=1,
        variables=["temperature_2m", "precipitation"],
    )
    assert set(df.columns) == {"temperature_2m", "precipitation"}
