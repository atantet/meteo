"""Tests d'intégration App 1 Veille — pipeline complet en mode dry-run."""

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
        "source_meteo": {
            "prevision": "openmeteo",
            "modeles": ["best_match"],
            "horizon_max_jours": 2,
        },
        "alertes": {
            "gel": {"actif": True, "seuil_celsius": 4.0},
            "canicule_aeration": {"actif": True, "seuil_celsius": 25.0},
            "canicule_stress": {"actif": True, "seuil_celsius": 30.0},
            "risque_maladies": {
                "actif": True,
                "t_min_nuit_celsius": 15.0,
            },
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


def _prevision_synthetique(t_celsius: float = 15.0) -> pd.DataFrame:
    """72 h de prévision homogène (horizon AROME France HD + marge mildiou).

    Inclut les colonnes nécessaires au calcul ETP socle (T, HR, vent,
    rayonnement). rayonnement_global=0 ⇒ ETP socle ~ aérodynamique
    seul, suffisant pour des tests d'orchestration où l'ETP exacte
    n'est pas le sujet.
    """
    index = pd.date_range("2024-06-15 00:00:00+00:00", periods=72, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(72, t_celsius + 273.15),
            "humidite_relative": np.full(72, 0.7),
            "precipitation": np.full(72, 0.0),
            "probabilite_pluie_pct": np.full(72, 0.0),
            "vitesse_vent_10m": np.full(72, 5.0),
            "rafales_vent_10m": np.full(72, 9.0),
            "direction_vent_deg": np.full(72, 270.0),
            "rayonnement_global": np.full(72, 0.0),
            "cloud_cover": np.full(72, 0.5),
        },
        index=index,
    )


def test_executer_veille_dry_run_capture_stdout() -> None:
    """Pipeline complet : source mockée → indicateurs → alertes → email → dry-run."""
    from apps.veille.__main__ import executer_veille

    mock_source = MagicMock()
    # 10 °C constant : > 4 (pas gel), < 15 (pas maladies), < 25 (pas canicule) → RAS.
    mock_source.obtenir_prevision.return_value = _prevision_synthetique(t_celsius=10.0)

    config = _config_test()
    now = pd.Timestamp("2024-06-15 04:30:00+00:00")

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = executer_veille(config, secrets=None, source=mock_source, now_utc=now)

    assert code == 0
    output = buf.getvalue()
    assert "dry-run" in output
    assert "Veille 2024-06-15 — RAS" in output  # pas d'alerte
    # Source appelée avec bons paramètres : on fetch horizon+1 jours (=3)
    # pour couvrir la fenêtre 48 h de l'envoi de l'après-midi (ancre 12 h
    # → fin à 12 h de J+2, sur une 3ᵉ journée).
    mock_source.obtenir_prevision.assert_called_once_with(
        latitude=48.5, longitude=-1.6, horizon_jours=3, past_days=1
    )


def test_apres_midi_couvre_8_periodes_avec_fenetre_fetch_reelle() -> None:
    """Garde-fou : l'envoi de l'après-midi couvre 8 périodes (comme le matin).

    Reproduit la fenêtre de données RÉELLE du fetch production (past_days=1
    + forecast_days = horizon+1 = 3) et vérifie que la grille de l'après-midi
    affiche bien 8 pictos sur 3 dates (J après-midi/soir, J+1 complet, J+2
    nuit/matin). Avec seulement forecast_days=2 (l'ancien bug), J+2 manquerait
    → 6 pictos. Ce test aurait attrapé l'incohérence.
    """
    from apps.veille.alertes import evaluer_alertes
    from apps.veille.email import composer_email
    from apps.veille.indicateurs import calculer_indicateurs

    # past_days=1 (14/06) + forecast_days=3 (15, 16, 17/06) → 4 jours.
    idx = pd.date_range("2024-06-14 00:00", "2024-06-17 23:00", freq="h", tz="UTC")
    n = len(idx)
    prevision = pd.DataFrame(
        {
            "temperature_2m": np.full(n, 12.0 + 273.15),
            "humidite_relative": np.full(n, 0.7),
            "precipitation": np.full(n, 0.0),
            "probabilite_pluie_pct": np.full(n, 0.0),
            "vitesse_vent_10m": np.full(n, 5.0),
            "rafales_vent_10m": np.full(n, 9.0),
            "direction_vent_deg": np.full(n, 270.0),
            "rayonnement_global": np.full(n, 0.0),
            "cloud_cover": np.full(n, 0.3),
            "weather_code": np.ones(n, dtype=int),
        },
        index=idx,
    )
    config = _config_test()
    # Envoi de l'après-midi : 17:30 UTC le 15 → ancre 12 h locale du 15.
    now = pd.Timestamp("2024-06-15 17:30:00+00:00")
    ind = calculer_indicateurs(prevision, now, config)
    alertes = evaluer_alertes(ind, config)
    email = composer_email(
        ind,
        alertes,
        config,
        now.to_pydatetime(),
        cartes_grille=None,
        vigilance=None,
        prevision_horaire=prevision,
    )
    # 8 périodes pavées (2 + 4 + 2) → 8 pictos. "data:image" (pas "...png")
    # car la fenêtre Nuit par ciel ~clair rend une icône SVG.
    assert email.html.count("data:image") == 8
    # La 3ᵉ date (J+2 = 17/06) doit être présente dans la grille.
    assert "17/06" in email.html


def test_executer_veille_alerte_gel_dans_email() -> None:
    """Avec T° très basse, l'alerte gel doit apparaître dans l'email dry-run."""
    from apps.veille.__main__ import executer_veille

    mock_source = MagicMock()
    mock_source.obtenir_prevision.return_value = _prevision_synthetique(t_celsius=-5.0)
    config = _config_test()
    now = pd.Timestamp("2024-06-15 04:30:00+00:00")

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = executer_veille(config, secrets=None, source=mock_source, now_utc=now)

    assert code == 0
    out = buf.getvalue()
    # T_min ≤ 4 °C → alerte unique « gel » (purge + voilage).
    assert "gel" in out.lower()
    assert "purger" in out.lower()
    assert "voiler" in out.lower()
    assert "-5.0" in out  # T° min affichée


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

    mock_source = MagicMock()
    mock_source.obtenir_prevision.return_value = _prevision_synthetique(t_celsius=15.0)

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
    now = pd.Timestamp("2024-06-15 04:30:00+00:00")

    with patch("apps.veille.sender.smtplib.SMTP") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        code = executer_veille(config, secrets=secrets, source=mock_source, now_utc=now)

    assert code == 0
    mock_smtp.assert_called_once_with("smtp.example.com", 587)
    mock_server.send_message.assert_called_once()
