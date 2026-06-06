"""Tests d'intégration App 1 Veille — pipeline complet (prévi MF, ADR-0014)."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _config_test() -> dict:
    return {
        "site": {"latitude": 48.5, "longitude": -1.6, "altitude": 30, "tz": "Europe/Paris"},
        "alertes": {
            "gel": {"actif": True, "seuil_celsius": 4.0},
            "canicule_aeration": {"actif": True, "seuil_celsius": 25.0},
            "canicule_stress": {"actif": True, "seuil_celsius": 30.0},
            "risque_maladies": {"actif": True, "t_min_nuit_celsius": 15.0},
            "pluie_intense": {"actif": True, "seuil_mm_24h": 20.0},
            "vent_fort": {"actif": True, "seuil_kmh": 60.0},
        },
        "indicateurs": {},
        "email": {
            "format": "html_mobile",
            "sujet_template": "Veille {date} — {alertes_resume}",
            "inclure_lien_fiches_indices": False,
            "url_fiches_indices": "",
        },
        "diffusion": {"envoi_reel": False},
    }


def _prevision_synthetique(
    t_celsius: float = 15.0, debut: str = "2024-06-15 00:00"
) -> pd.DataFrame:
    """72 h de prévision horaire homogène, colonnes socle (comme la source MF)."""
    index = pd.date_range(debut, periods=72, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(72, t_celsius + 273.15),
            "humidite_relative": np.full(72, 0.7),
            "precipitation": np.full(72, 0.0),
            "probabilite_pluie_pct": np.full(72, 0.0),
            "vitesse_vent_10m": np.full(72, 5.0),
            "rafales_vent_10m": np.full(72, 9.0),
            "direction_vent_deg": np.full(72, 270.0),
            "cloud_cover": np.full(72, 0.5),
            "weather_code": pd.array([1] * 72, dtype="Int64"),
        },
        index=index,
    )


def _prevision_mf(df: pd.DataFrame):
    """Enrobe une prévision synthétique dans un ``PrevisionMF`` (source officielle)."""
    from meteo_socle.sources.meteofrance_officiel import PrevisionMF

    return PrevisionMF(
        df=df,
        updated_on=pd.Timestamp("2024-06-15 05:30", tz="UTC"),
        position={"name": "Sains", "timezone": "Europe/Paris"},
    )


def test_executer_veille_dry_run_capture_stdout() -> None:
    """Pipeline complet : source MF mockée → indicateurs → alertes → email → dry-run."""
    from apps.veille.__main__ import executer_veille

    config = _config_test()
    now = pd.Timestamp("2024-06-15 06:00:00+00:00")
    mock_source = MagicMock()
    # 10 °C constant → ni gel (>4), ni maladies (<15), ni canicule (<25) → RAS.
    mock_source.obtenir_prevision.return_value = _prevision_mf(_prevision_synthetique(10.0))

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = executer_veille(config, secrets=None, source=mock_source, now_utc=now)

    assert code == 0
    output = buf.getvalue()
    assert "dry-run" in output
    assert "Veille 2024-06-15 — RAS" in output
    # Source MF appelée au point (lat/lon), sans run ni horizon (ADR-0014).
    mock_source.obtenir_prevision.assert_called_once_with(latitude=48.5, longitude=-1.6)


def test_grille_couvre_plusieurs_periodes() -> None:
    """La grille du mail couvre plusieurs périodes 6 h (pictos depuis weather_code MF)."""
    from apps.veille.alertes import evaluer_alertes
    from apps.veille.email import composer_email
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(12.0, debut="2024-06-15 04:00")
    config = _config_test()
    now = pd.Timestamp("2024-06-15 17:30:00+00:00")
    ind = calculer_indicateurs(prevision, now, config)
    alertes = evaluer_alertes(ind, config)
    email = composer_email(ind, alertes, config, now.to_pydatetime(), prevision_horaire=prevision)
    assert "Tendance jusqu" in email.html
    assert email.html.count("data:image") >= 6


def test_executer_veille_alerte_gel_dans_email() -> None:
    """Avec T° très basse, l'alerte gel doit apparaître dans l'email dry-run."""
    from apps.veille.__main__ import executer_veille

    config = _config_test()
    now = pd.Timestamp("2024-06-15 06:00:00+00:00")
    mock_source = MagicMock()
    mock_source.obtenir_prevision.return_value = _prevision_mf(_prevision_synthetique(-5.0))

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = executer_veille(config, secrets=None, source=mock_source, now_utc=now)

    assert code == 0
    out = buf.getvalue()
    assert "gel" in out.lower()
    assert "purger" in out.lower()
    assert "voiler" in out.lower()
    assert "-5.0" in out


def test_executer_veille_http_error_returns_2() -> None:
    """HTTPError lors du fetch source → exit code 2."""
    import requests

    from apps.veille.__main__ import executer_veille

    mock_source = MagicMock()
    mock_source.obtenir_prevision.side_effect = requests.HTTPError("500")
    config = _config_test()
    now = pd.Timestamp("2024-06-15 04:30:00+00:00")

    code = executer_veille(config, secrets=None, source=mock_source, now_utc=now)
    assert code == 2


def test_executer_veille_envoi_reel_appelle_smtp() -> None:
    """En mode envoi_reel=True, vérifie que envoyer() invoque le SMTP."""
    from apps.veille.__main__ import executer_veille

    config = _config_test()
    config["diffusion"]["envoi_reel"] = True
    secrets = {
        "host": "smtp.example.com",
        "port": 587,
        "user": "u@example.com",
        "password": "pwd",
        "email_from": "u@example.com",
        "email_to": ["dest@example.com"],
    }
    now = pd.Timestamp("2024-06-15 06:00:00+00:00")
    mock_source = MagicMock()
    mock_source.obtenir_prevision.return_value = _prevision_mf(_prevision_synthetique(15.0))

    with patch("apps.veille.sender.smtplib.SMTP") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        code = executer_veille(config, secrets=secrets, source=mock_source, now_utc=now)

    assert code == 0
    mock_smtp.assert_called_once_with("smtp.example.com", 587)
    mock_server.send_message.assert_called_once()


def _mf_payload(t_celsius: float = 12.0, n: int = 48, debut: str = "2024-06-15 04:00") -> dict:
    """Payload JSON du webservice MF (unités natives : °C, %, m/s, mm)."""
    idx = pd.date_range(debut, periods=n, freq="h", tz="UTC")
    forecast = [
        {
            "dt": int(ts.timestamp()),
            "T": {"value": t_celsius},
            "humidity": 70,
            "wind": {"speed": 5, "gust": 9, "direction": 270},
            "rain": {"1h": 0.0},
            "clouds": 50,
            "weather": {"icon": "p1j", "desc": "Peu nuageux"},
        }
        for ts in idx
    ]
    prob = [{"dt": int(idx[0].timestamp()), "rain": {"3h": 10, "6h": None}}]
    return {
        "updated_on": int(idx[0].timestamp()),
        "position": {"name": "Sains", "timezone": "Europe/Paris"},
        "forecast": forecast,
        "probability_forecast": prob,
    }


def test_executer_veille_pipeline_complet_mf_offline() -> None:
    """Pipeline COMPLET offline : mock session → MeteoFranceOfficiel réel → dry-run.

    Exerce le fetch + parsing/conversions socle + indicateurs + email, sans réseau.
    Vérifie que le label « Source » reflète la prévision officielle MF (ADR-0014).
    """
    from apps.veille.__main__ import executer_veille
    from meteo_socle.sources.meteofrance_officiel import MeteoFranceOfficiel

    def _resp(payload: dict) -> MagicMock:
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = payload
        r.raise_for_status = MagicMock()
        return r

    sess = MagicMock()
    sess.get.side_effect = lambda url, params=None, timeout=None: _resp(_mf_payload())

    source = MeteoFranceOfficiel(session=sess)
    config = _config_test()
    now = pd.Timestamp("2024-06-15 06:00:00+00:00")

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = executer_veille(config, secrets=None, source=source, now_utc=now)

    assert code == 0
    out = buf.getvalue()
    # Un seul appel HTTP (JSON au point, pas de run).
    assert sess.get.call_count == 1
    # Label « Source » = prévision officielle MF (avec fraîcheur).
    assert "Prévision officielle Météo-France" in out
