"""Tests unitaires `meteo_socle.sources.openmeteo_archive` (mock HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_payload() -> dict:
    """Réponse Open-Meteo archive synthétique pour 3 h."""
    return {
        "latitude": 48.5,
        "longitude": -1.6,
        "elevation": 30.0,
        "hourly": {
            "time": ["2020-06-15T00:00", "2020-06-15T01:00", "2020-06-15T02:00"],
            "temperature_2m": [10.0, 9.5, 9.0],
            "relative_humidity_2m": [80.0, 85.0, 88.0],
            "precipitation": [0.0, 0.3, 0.0],
            "wind_speed_10m": [4.0, 3.5, 3.0],
            "shortwave_radiation": [0.0, 0.0, 0.0],
            "et0_fao_evapotranspiration": [0.02, 0.01, 0.01],
        },
    }


def test_obtenir_historique_conversions(fake_payload: dict) -> None:
    from meteo_socle.sources.openmeteo_archive import OpenMeteoArchive

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = fake_payload
    mock_session.get.return_value = mock_response

    client = OpenMeteoArchive(session=mock_session)
    df = client.obtenir_historique(
        latitude=48.5, longitude=-1.6, start_date="2020-06-15", end_date="2020-06-15"
    )

    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"
    assert df["temperature_2m"].iloc[0] == pytest.approx(283.15)
    assert df["humidite_relative"].iloc[0] == pytest.approx(0.80)
    assert df["etp_open_meteo"].iloc[0] == pytest.approx(0.02)


def test_obtenir_historique_params(fake_payload: dict) -> None:
    from meteo_socle.sources.openmeteo_archive import OpenMeteoArchive

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = fake_payload
    mock_session.get.return_value = mock_response

    client = OpenMeteoArchive(modele="era5", session=mock_session)
    client.obtenir_historique(
        latitude=48.5, longitude=-1.6, start_date="1991-01-01", end_date="2020-12-31"
    )

    args, kwargs = mock_session.get.call_args
    assert args[0] == "https://archive-api.open-meteo.com/v1/archive"
    p = kwargs["params"]
    assert p["start_date"] == "1991-01-01"
    assert p["end_date"] == "2020-12-31"
    assert p["models"] == "era5"
    assert p["timezone"] == "UTC"
    assert "temperature_2m" in p["hourly"]


def test_obtenir_historique_http_error_non_retryable(fake_payload: dict) -> None:
    """Erreur HTTP non-retryable (ex. 400) propage immédiatement."""
    import requests

    from meteo_socle.sources.openmeteo_archive import OpenMeteoArchive

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.raise_for_status.side_effect = requests.HTTPError("400")
    mock_session.get.return_value = mock_response

    client = OpenMeteoArchive(session=mock_session)
    with pytest.raises(requests.HTTPError):
        client.obtenir_historique(
            latitude=0, longitude=0, start_date="2020-01-01", end_date="2020-01-02"
        )
    # Une seule tentative pour non-retryable.
    assert mock_session.get.call_count == 1


def test_obtenir_historique_retry_429(fake_payload: dict, monkeypatch) -> None:
    """Sur 429, retry jusqu'à 4 fois avec backoff (time.sleep mocké)."""
    from meteo_socle.sources import openmeteo_archive
    from meteo_socle.sources.openmeteo_archive import OpenMeteoArchive

    # 3 fois 429, puis succès.
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {}
    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.json.return_value = fake_payload

    mock_session = MagicMock()
    mock_session.get.side_effect = [resp_429, resp_429, resp_429, resp_ok]

    attentes: list[float] = []
    monkeypatch.setattr(openmeteo_archive.time, "sleep", attentes.append)

    client = OpenMeteoArchive(session=mock_session)
    df = client.obtenir_historique(
        latitude=0, longitude=0, start_date="2020-01-01", end_date="2020-01-02"
    )
    assert len(df) == 3
    assert mock_session.get.call_count == 4
    # Backoff exponentiel : 5, 10, 20 s.
    assert attentes == [5.0, 10.0, 20.0]


def test_obtenir_historique_retry_epuise(fake_payload: dict, monkeypatch) -> None:
    """Si les 4 tentatives sont toutes 429, on lève HTTPError."""
    import requests

    from meteo_socle.sources import openmeteo_archive
    from meteo_socle.sources.openmeteo_archive import OpenMeteoArchive

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {}
    resp_429.raise_for_status.side_effect = requests.HTTPError("429")

    mock_session = MagicMock()
    mock_session.get.return_value = resp_429

    monkeypatch.setattr(openmeteo_archive.time, "sleep", lambda _: None)

    client = OpenMeteoArchive(session=mock_session)
    with pytest.raises(requests.HTTPError):
        client.obtenir_historique(
            latitude=0, longitude=0, start_date="2020-01-01", end_date="2020-01-02"
        )
    assert mock_session.get.call_count == 4
