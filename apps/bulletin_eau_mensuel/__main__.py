"""Point d'entrée — Bulletin eau mensuel.

Usage : ``python -m apps.bulletin_eau_mensuel [--preview PATH]``

Pipeline :

1. Charge config YAML (+ override local) + .env.
2. Collecte les trois piliers (nappe, restrictions, pluie) — dégradation
   gracieuse si une source échoue.
3. Compose l'email (sujet + texte + HTML).
4. Envoie via SMTP (réutilise ``apps.veille.sender``) ou imprime en dry-run.

Exit code : 0 succès / dry-run / preview ; 1 erreur config ; 3 erreur envoi.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from apps.veille.sender import envoyer

from .config import ConfigError, load_config, load_dotenv_if_present, load_smtp_secrets
from .donnees import collecter_bulletin
from .email import composer_bulletin_email

logger = logging.getLogger(__name__)


def executer_bulletin(
    config: dict[str, Any],
    secrets: dict[str, Any] | None,
    now_utc: pd.Timestamp | None = None,
    preview_path: str | Path | None = None,
) -> int:
    """Exécute le pipeline bulletin de bout en bout."""
    bulletin = collecter_bulletin(config, now_utc=now_utc)
    email = composer_bulletin_email(bulletin)

    if preview_path is not None:
        try:
            p = Path(preview_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(email.html, encoding="utf-8")
            logger.info("Preview HTML écrit : %s", p)
        except OSError as e:
            logger.error("Erreur écriture preview : %s", e)
            return 3
        return 0

    envoi_reel = config.get("diffusion", {}).get("envoi_reel", False)
    try:
        envoyer(email, secrets=secrets, envoi_reel=envoi_reel)
    except Exception as e:  # noqa: BLE001 — log + sortie propre
        logger.error("Erreur envoi SMTP : %s", e)
        return 3
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m apps.bulletin_eau_mensuel",
        description="Bulletin eau mensuel — état de la ressource (mail).",
    )
    parser.add_argument(
        "--preview",
        type=str,
        metavar="PATH",
        default=None,
        help="Écrit le HTML composé dans PATH au lieu d'envoyer (pas de secret requis).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    load_dotenv_if_present()
    try:
        config = load_config()
    except (FileNotFoundError, ConfigError) as e:
        logger.error("Erreur chargement config : %s", e)
        return 1

    secrets: dict[str, Any] | None = None
    if args.preview is None and config.get("diffusion", {}).get("envoi_reel", False):
        try:
            secrets = load_smtp_secrets()
        except ConfigError as e:
            logger.error("Secret SMTP manquant : %s", e)
            return 1

    return executer_bulletin(config, secrets, preview_path=args.preview)


if __name__ == "__main__":
    sys.exit(main())
