"""Point d'entrée App 1 Veille — orchestration complète.

Usage : ``python -m apps.veille``

Pipeline :

1. Charge config YAML (défaut + override local) + .env.
2. Query Open-Meteo pour la prévision 7 j au site configuré.
3. Calcule les indicateurs Veille.
4. Évalue les alertes seuils.
5. Compose l'email (sujet + texte + HTML).
6. Envoie via SMTP (ou imprime en stdout si envoi_reel=False).

Exit code :
- 0 : succès (mail envoyé ou imprimé en dry-run).
- 1 : erreur configuration.
- 2 : erreur source météo.
- 3 : erreur SMTP.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from meteo_socle.sources.meteofrance_vigilance import recuperer_vigilance
from meteo_socle.sources.openmeteo import OpenMeteoForecast

from .alertes import evaluer_alertes
from .cartes_synoptiques import recuperer_cartes
from .charts import graphique_48h_base64
from .config import (
    ConfigError,
    load_config,
    load_dotenv_if_present,
    load_smtp_secrets,
)
from .email import composer_email
from .indicateurs import calculer_indicateurs
from .sender import envoyer

logger = logging.getLogger(__name__)


def executer_veille(
    config: dict[str, Any],
    secrets: dict[str, Any] | None,
    source: OpenMeteoForecast | None = None,
    now_utc: pd.Timestamp | None = None,
    preview_path: str | Path | None = None,
) -> int:
    """Exécute le pipeline Veille de bout en bout.

    Parameters
    ----------
    config :
        Configuration Veille (cf. ``config.load_config``).
    secrets :
        Secrets SMTP. Peut être ``None`` si dry-run ou preview.
    source :
        Source météo injectable (tests). Si ``None``, un
        ``OpenMeteoForecast`` est créé avec le 1er modèle de la config.
    now_utc :
        Référence temporelle. Si ``None``, ``pd.Timestamp.now(tz='UTC')``.
    preview_path :
        Si fourni, force l'envoi en mode preview : écrit le HTML
        composé dans ce chemin et n'envoie rien par SMTP. Utile pour
        prévisualiser le rendu sans bombarder son inbox.

    Returns
    -------
    int
        Code de retour (0 succès, 2 HTTP source, 3 SMTP / écriture).
    """
    if source is None:
        # Liste de modèles → chaîne séparée par des virgules : Open-Meteo
        # renvoie les colonnes par modèle, le socle les fusionne par
        # priorité (1er = prioritaire). Cf. config source_meteo.modeles.
        modeles = config["source_meteo"]["modeles"]
        source = OpenMeteoForecast(modele=",".join(modeles))
    if now_utc is None:
        now_utc = pd.Timestamp.now(tz="UTC")

    site = config["site"]
    horizon = config["source_meteo"]["horizon_max_jours"]
    # On fetch UN jour de plus que l'horizon d'affichage (48 h). La
    # fenêtre fait toujours 48 h, mais elle est ancrée sur la demi-journée
    # (00 h le matin, 12 h l'après-midi). L'ancre 12 h pousse la fin de
    # fenêtre jusqu'à 12 h de J+2 → il faut une 3ᵉ journée de prévision,
    # sinon la Nuit/le Matin de J+2 manquent (grille à 6 périodes au lieu
    # de 8). Le matin n'en utilise que 2 ; le jour en trop est inoffensif.
    fetch_jours = horizon + 1
    logger.info(
        "Fetch Open-Meteo lat=%.4f lon=%.4f horizon=%d j (fetch %d j)",
        site["latitude"],
        site["longitude"],
        horizon,
        fetch_jours,
    )
    try:
        # past_days=1 pour récupérer la portion 00 h 00 → T+0 du jour
        # courant (heures déjà passées), afin que la grille Tendance et
        # le graphique 48 h couvrent réellement [ancre ; ancre+48 h]
        # plutôt que [T+0 ; T+0+48 h]. Indicateurs et alertes filtrent
        # par ailleurs sur le futur (>= now_utc).
        prevision = source.obtenir_prevision(
            latitude=site["latitude"],
            longitude=site["longitude"],
            horizon_jours=fetch_jours,
            past_days=1,
        )
    except requests.HTTPError as e:
        logger.error("Erreur HTTP source météo : %s", e)
        return 2

    ind = calculer_indicateurs(prevision, now_utc, config)
    alertes = evaluer_alertes(ind, config)
    logger.info("%d alerte(s) déclenchée(s)", len(alertes))

    tz_locale = config["site"].get("tz", "Europe/Paris")
    chart = graphique_48h_base64(prevision, now_utc, tz_locale=tz_locale)
    # Grille 3×2 : Met Office (gauche, fronts Atlantique nord/Europe) +
    # AROME mode 24 (droite, France précip+pression+nébulosité), pour
    # T+0 / T+24 / T+48 du run 00 UTC. Cartes manquantes sautées
    # silencieusement (mail envoyé même si une source est down).
    cartes_grille = recuperer_cartes(now_utc=now_utc)
    # Vigilance MF (officielle d'État) — référence pour orages, vent,
    # pluie, canicule, neige-verglas, grand froid sur 0-48 h. Si la clé
    # API METEOFRANCE_TOKEN est absente, retourne None et le bloc est
    # silencieusement skippé (mail livré sans Vigilance).
    departement = str(config.get("vigilance_mf", {}).get("departement", "35"))
    vigilance = recuperer_vigilance(departement=departement)
    email = composer_email(
        ind,
        alertes,
        config,
        now_utc.to_pydatetime(),
        chart_48h_base64=chart,
        cartes_grille=cartes_grille,
        vigilance=vigilance,
        prevision_horaire=prevision,
    )

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

    envoi_reel = config["diffusion"]["envoi_reel"]
    try:
        envoyer(email, secrets=secrets, envoi_reel=envoi_reel)
    except Exception as e:  # noqa: BLE001 — on log et on quitte proprement
        logger.error("Erreur envoi SMTP : %s", e)
        return 3
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m apps.veille",
        description="Veille météo matinale — pipeline App 1.",
    )
    parser.add_argument(
        "--preview",
        type=str,
        metavar="PATH",
        default=None,
        help=(
            "Écrit le HTML composé dans PATH au lieu d'envoyer par SMTP. "
            "Aucun secret SMTP requis. Ouvrir ensuite le fichier dans un "
            "navigateur pour prévisualiser."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point CLI : charge config + secrets puis exécute le pipeline."""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    load_dotenv_if_present()
    try:
        config = load_config()
    except (FileNotFoundError, ConfigError) as e:
        logger.error("Erreur chargement config : %s", e)
        return 1

    secrets: dict[str, Any] | None = None
    # En mode --preview, aucun secret SMTP n'est requis.
    if args.preview is None and config["diffusion"]["envoi_reel"]:
        try:
            secrets = load_smtp_secrets()
        except ConfigError as e:
            logger.error("Secret SMTP manquant : %s", e)
            return 1

    return executer_veille(config, secrets, preview_path=args.preview)


if __name__ == "__main__":
    sys.exit(main())
