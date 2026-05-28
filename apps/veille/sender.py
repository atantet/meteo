"""Envoi SMTP de l'email composé.

Utilise ``smtplib.SMTP`` avec STARTTLS — supporte tous les providers
documentés dans ``.env.example`` (Gmail, Posteo, OVH).

En mode dry-run (``envoi_reel=False`` dans la config), n'envoie pas et
imprime le sujet + texte sur stdout. Utile en local pour valider la
mise en page sans envoyer réellement.
"""

from __future__ import annotations

import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from .email import EmailComposed


def construire_message(email: EmailComposed, email_from: str, email_to: list[str]) -> MIMEMultipart:
    """Construit un MIMEMultipart 'alternative' avec texte + HTML."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = email.sujet
    msg["From"] = email_from
    msg["To"] = ", ".join(email_to)
    msg.attach(MIMEText(email.texte, "plain", "utf-8"))
    msg.attach(MIMEText(email.html, "html", "utf-8"))
    return msg


def envoyer_smtp(email: EmailComposed, secrets: dict[str, Any], smtp_class=None) -> None:
    """Envoie le message via SMTP STARTTLS.

    Parameters
    ----------
    email :
        Email composé (sujet + texte + HTML).
    secrets :
        Dict issu de ``config.load_smtp_secrets`` (host, port, user,
        password, email_from, email_to).
    smtp_class :
        Classe SMTP — injectable pour les tests (par ex.
        ``unittest.mock.MagicMock``). Résolu à la volée pour permettre
        ``patch("apps.veille.sender.smtplib.SMTP")``.
    """
    if smtp_class is None:
        smtp_class = smtplib.SMTP
    msg = construire_message(email, secrets["email_from"], secrets["email_to"])
    with smtp_class(secrets["host"], secrets["port"]) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(secrets["user"], secrets["password"])
        server.send_message(msg)


def envoyer_dry_run(email: EmailComposed, stream=None) -> None:
    """Mode dry-run : imprime sujet + texte sur stdout, n'envoie rien."""
    out = stream if stream is not None else sys.stdout
    out.write(f"[dry-run] Sujet : {email.sujet}\n")
    out.write("-" * 60 + "\n")
    out.write(email.texte + "\n")
    out.write("-" * 60 + "\n")


def envoyer(
    email: EmailComposed,
    secrets: dict[str, Any] | None,
    envoi_reel: bool,
    smtp_class=None,
    stream=None,
) -> None:
    """Dispatch : envoi réel ou dry-run selon flag config."""
    if envoi_reel:
        if secrets is None:
            raise ValueError("envoi_reel=True mais secrets=None")
        envoyer_smtp(email, secrets, smtp_class=smtp_class)
    else:
        envoyer_dry_run(email, stream=stream)
