"""Envoi SMTP de l'email composé.

Utilise ``smtplib.SMTP`` avec STARTTLS — supporte tous les providers
documentés dans ``.env.example`` (Gmail, Posteo, OVH).

En mode dry-run (``envoi_reel=False`` dans la config), n'envoie pas et
imprime le sujet + texte sur stdout. Utile en local pour valider la
mise en page sans envoyer réellement.
"""

from __future__ import annotations

import base64
import re
import smtplib
import sys
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from .email import EmailComposed

# Repère les images encodées en data-URI (``src="data:image/png;base64,…"``).
# Le groupe base64 s'arrête naturellement au guillemet fermant (hors alphabet b64).
_DATA_URI_IMAGE = re.compile(r"data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+)")


def _images_inline_cid(html: str) -> tuple[str, list[tuple[str, str, bytes]]]:
    """data-URI images → références ``cid:``, avec **déduplication par contenu**.

    Certains webmails (Roundcube/Posteo) n'affichent pas certaines images en
    data-URI ; les images *inline* via Content-ID (méthode email standard) passent
    partout. Bonus : une image répétée (pictos ciel, flèches ETP sur toute la
    grille) n'est jointe **qu'une fois** → mail plus léger.

    Renvoie le HTML réécrit + la liste ``(cid, sous_type, octets)`` des images
    uniques à joindre en parties MIME inline.
    """
    images: list[tuple[str, str, bytes]] = []
    cid_par_donnee: dict[tuple[str, str], str] = {}

    def _vers_cid(m: re.Match[str]) -> str:
        sous_type, donnees_b64 = m.group(1), m.group(2)
        cle = (sous_type, donnees_b64)
        cid = cid_par_donnee.get(cle)
        if cid is None:
            cid = f"img{len(cid_par_donnee)}@veille"
            cid_par_donnee[cle] = cid
            images.append((cid, sous_type, base64.b64decode(donnees_b64)))
        return f"cid:{cid}"

    return _DATA_URI_IMAGE.sub(_vers_cid, html), images


def construire_message(email: EmailComposed, email_from: str, email_to: list[str]) -> MIMEMultipart:
    """Construit le message : texte + HTML, images data-URI converties en inline CID.

    Structure ``multipart/related`` [ ``multipart/alternative`` (texte + HTML) +
    images inline ]. S'il n'y a aucune image, on garde un simple
    ``multipart/alternative`` (cas du mail d'échec).
    """
    html, images = _images_inline_cid(email.html)
    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(email.texte, "plain", "utf-8"))
    alternative.attach(MIMEText(html, "html", "utf-8"))

    if not images:
        msg: MIMEMultipart = alternative
    else:
        msg = MIMEMultipart("related", type="multipart/alternative")
        msg.attach(alternative)
        for cid, sous_type, donnees in images:
            part = MIMEImage(donnees, _subtype=sous_type)
            part.add_header("Content-ID", f"<{cid}>")
            part.add_header("Content-Disposition", "inline")
            msg.attach(part)

    msg["Subject"] = email.sujet
    msg["From"] = email_from
    msg["To"] = ", ".join(email_to)
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
