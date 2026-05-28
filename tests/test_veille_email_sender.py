"""Tests `apps.veille.email` + `apps.veille.sender`."""

from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


CONFIG_TEST = {
    "email": {
        "format": "html_mobile",
        "sujet_template": "Veille {date} — {alertes_resume}",
        "inclure_lien_fiches_indices": True,
        "url_fiches_indices": "https://example.com/fiches",
    }
}


def _ind(**kwargs):
    from apps.veille.indicateurs import IndicateursVeille

    defaults = dict(
        temperature_min_24h_celsius=8.0,
        temperature_max_24h_celsius=18.0,
        cumul_pluie_24h_mm=2.5,
        cumul_pluie_48h_mm=5.0,
        cumul_pluie_72h_mm=8.0,
        vent_max_24h_kmh=20.0,
        rafales_max_24h_kmh=35.0,
        etp_jour_mm=3.2,
        bilan_eau_7j_mm=-5.0,
        prob_pluie_max_24h_pct=15.0,
        prob_pluie_max_48h_pct=30.0,
        prob_pluie_max_72h_pct=45.0,
        tension_irrigation=False,
    )
    defaults.update(kwargs)
    return IndicateursVeille(**defaults)


def _alerte_gel():
    from apps.veille.alertes import Alerte

    return Alerte("gel", "critique", "Gel — T° min −3.0 °C", -3.0, "°C", -2.0)


def test_composer_sujet_ras() -> None:
    from apps.veille.email import composer_sujet

    sujet = composer_sujet([], datetime(2024, 6, 15, 7, 30), "Veille {date} — {alertes_resume}")
    assert sujet == "Veille 2024-06-15 — RAS"


def test_composer_sujet_avec_alertes() -> None:
    from apps.veille.email import composer_sujet

    sujet = composer_sujet(
        [_alerte_gel()],
        datetime(2024, 6, 15),
        "Veille {date} — {alertes_resume}",
    )
    assert "gel" in sujet
    assert "2024-06-15" in sujet


def test_composer_texte_contient_alertes_et_indicateurs() -> None:
    from apps.veille.email import composer_texte

    txt = composer_texte(_ind(), [_alerte_gel()], datetime(2024, 6, 15, 7, 30))
    assert "ALERTES" in txt
    assert "Gel" in txt
    assert "INDICATEURS" in txt
    assert "Bilan P-ETP" in txt or "Bilan" in txt
    # Valeurs présentes.
    assert "8.0" in txt or "8" in txt  # T° min
    assert "informationnel" in txt.lower()
    # Footer source visible.
    assert "Open-Meteo" in txt
    assert "FAO" in txt


def test_composer_texte_aucune_alerte() -> None:
    from apps.veille.email import composer_texte

    txt = composer_texte(_ind(), [], datetime(2024, 6, 15, 7, 30))
    assert "Aucune alerte" in txt


def test_composer_html_structure() -> None:
    from apps.veille.email import composer_html

    html = composer_html(_ind(), [_alerte_gel()], datetime(2024, 6, 15, 7, 30))
    assert "<!DOCTYPE html>" in html
    assert 'name="viewport"' in html  # responsive mobile
    assert "Gel" in html
    assert "T° min nuit" in html
    # Footer source + ETP discret.
    assert "Open-Meteo" in html
    assert "FAO" in html


def test_composer_email_bundle() -> None:
    from apps.veille.email import composer_email

    result = composer_email(_ind(), [], CONFIG_TEST, datetime(2024, 6, 15, 7, 30))
    assert result.sujet == "Veille 2024-06-15 — RAS"
    assert "INDICATEURS" in result.texte
    assert "<!DOCTYPE html>" in result.html


def test_construire_message_multipart() -> None:
    from apps.veille.email import EmailComposed
    from apps.veille.sender import construire_message

    email = EmailComposed(sujet="S", texte="T", html="<p>H</p>")
    msg = construire_message(email, "a@b.com", ["c@d.com", "e@f.com"])
    assert msg["Subject"] == "S"
    assert msg["From"] == "a@b.com"
    assert msg["To"] == "c@d.com, e@f.com"
    payloads = msg.get_payload()
    assert len(payloads) == 2  # texte + html


def test_envoyer_dry_run() -> None:
    from apps.veille.email import EmailComposed
    from apps.veille.sender import envoyer_dry_run

    email = EmailComposed(sujet="Sujet test", texte="Corps texte", html="<p>H</p>")
    stream = io.StringIO()
    envoyer_dry_run(email, stream=stream)
    output = stream.getvalue()
    assert "Sujet test" in output
    assert "Corps texte" in output
    assert "dry-run" in output


def test_envoyer_dispatch_dry_run() -> None:
    from apps.veille.email import EmailComposed
    from apps.veille.sender import envoyer

    email = EmailComposed(sujet="S", texte="T", html="H")
    stream = io.StringIO()
    envoyer(email, secrets=None, envoi_reel=False, stream=stream)
    assert "dry-run" in stream.getvalue()


def test_envoyer_smtp_mock() -> None:
    """Vérifie le pattern d'appel SMTP : ehlo / starttls / login / send_message."""
    from apps.veille.email import EmailComposed
    from apps.veille.sender import envoyer_smtp

    email = EmailComposed(sujet="S", texte="T", html="<p>H</p>")
    secrets = {
        "host": "smtp.gmail.com",
        "port": 587,
        "user": "test@gmail.com",
        "password": "abcd",
        "email_from": "test@gmail.com",
        "email_to": ["dest@example.com"],
    }
    mock_smtp = MagicMock()
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    envoyer_smtp(email, secrets, smtp_class=mock_smtp)

    mock_smtp.assert_called_once_with("smtp.gmail.com", 587)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("test@gmail.com", "abcd")
    mock_server.send_message.assert_called_once()


def test_envoyer_envoi_reel_sans_secrets_raise() -> None:
    from apps.veille.email import EmailComposed
    from apps.veille.sender import envoyer

    email = EmailComposed(sujet="S", texte="T", html="H")
    with pytest.raises(ValueError):
        envoyer(email, secrets=None, envoi_reel=True)
