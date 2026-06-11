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
- 2 : erreur source météo (prévi MF) → mail d'échec envoyé.
- 3 : erreur SMTP.
- 4 : erreur de composition inattendue → mail d'échec envoyé.

Dès qu'un envoi échoue (codes 2/4), un **mail d'échec** avec le maximum d'infos
de debug (étape, exception, trace, contexte) est envoyé en plus de l'alerte
GitHub Actions, pour accélérer le diagnostic.
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from meteo_socle.sources.meteofrance_officiel import (
    MeteoFranceOfficiel,
    PrevisionIndisponibleError,
)
from meteo_socle.sources.meteofrance_vigilance import recuperer_vigilance

from .alertes import evaluer_alertes
from .anomalies import Anomalie
from .cartes_synoptiques import recuperer_cartes
from .charts import graphique_48h_base64
from .config import (
    ConfigError,
    load_config,
    load_dotenv_if_present,
    load_smtp_secrets,
)
from .email import composer_email, composer_email_echec
from .indicateurs import calculer_indicateurs, moment_envoi
from .semaine import executer_semaine
from .sender import envoyer

logger = logging.getLogger(__name__)


def _envoyer_echec(
    config: dict[str, Any],
    secrets: dict[str, Any] | None,
    now_utc: pd.Timestamp,
    preview_path: str | Path | None,
    etape: str,
    exc: BaseException,
) -> None:
    """Toujours notifier un échec dur : mail avec étape + trace + contexte.

    En plus de l'alerte GitHub Actions, on envoie un mail dédié pour accélérer le
    debug. Best-effort : ne relève jamais (un échec du mail d'échec est juste
    journalisé). En preview, le HTML d'échec est écrit dans ``preview_path``.
    """
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        email_echec = composer_email_echec(config, now_utc.to_pydatetime(), etape, exc, trace)
        if preview_path is not None:
            Path(preview_path).write_text(email_echec.html, encoding="utf-8")
            logger.info("Mail d'échec écrit en preview : %s", preview_path)
            return
        envoyer(email_echec, secrets=secrets, envoi_reel=config["diffusion"]["envoi_reel"])
        logger.info("Mail d'échec envoyé (étape : %s).", etape)
    except Exception as e2:  # noqa: BLE001 — le mail d'échec ne doit jamais relancer
        logger.error("Mail d'échec impossible à envoyer (%s) : %s", etape, e2)


def _prevision_repli_arpege(config: dict[str, Any], now_utc: pd.Timestamp, source: Any = None):
    """Repli 48 h sur ARPEGE Single Runs (Open-Meteo) quand le webservice MF pend.

    ARPEGE-Europe via Open-Meteo reste joignable depuis le runner même quand le
    webservice MF time out (blocage réseau MF↔datacenter). Le run ARPEGE renvoie
    les **mêmes colonnes socle** que la prévi MF (il manque seulement la proba
    calibrée → NaN) → pipeline 48 h inchangé. Mode dégradé : picto WMO ARPEGE (pas
    WWMF), pas de proba calibrée. Renvoie ``None`` si ARPEGE est aussi muet.
    """
    from meteo_socle.sources.meteofrance_officiel import PrevisionMF
    from meteo_socle.sources.openmeteo_runs import (
        ARPEGE,
        VARS_MONO_MODELE,
        OpenMeteoSingleRuns,
        creneau_run,
        runs_du_creneau,
    )

    site = config["site"]
    creneau, jour = creneau_run(now_utc)
    run = runs_du_creneau(creneau, jour)[ARPEGE]
    src = source or OpenMeteoSingleRuns()
    df = src.obtenir_run(ARPEGE, run, site["latitude"], site["longitude"], 4, VARS_MONO_MODELE)
    if df is None or df.empty:
        return None
    df = df.copy()
    if "weather_code" in df.columns:
        df["weather_code"] = df["weather_code"].astype("Int64")
    if "probabilite_pluie_pct" not in df.columns:
        df["probabilite_pluie_pct"] = pd.Series(index=df.index, dtype="float64")
    return PrevisionMF(
        df=df,
        updated_on=run,
        position={"name": "ARPEGE-Europe (repli)", "timezone": site.get("tz", "Europe/Paris")},
    )


def executer_veille(
    config: dict[str, Any],
    secrets: dict[str, Any] | None,
    source: MeteoFranceOfficiel | None = None,
    now_utc: pd.Timestamp | None = None,
    preview_path: str | Path | None = None,
    inclure_semaine: bool = True,
    semaine_source: Any = None,
    fetch_cartes_semaine: bool = True,
    fallback_mf: bool = False,
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
    inclure_semaine :
        Si ``False``, n'ajoute jamais la section semaine (utile pour les
        tests offline du seul pipeline 48 h, sans fetch réseau).
    semaine_source :
        Client ``OpenMeteoSingleRuns`` injectable pour la section semaine
        (tests). ``None`` → un client réel est créé par ``executer_semaine``.
    fetch_cartes_semaine :
        Passé à ``executer_semaine`` ; ``False`` désactive le fetch réseau
        des cartes ARPEGE-Europe (tests).
    fallback_mf :
        Si ``True`` et que la prévi MF est injoignable, replie le 48 h sur ARPEGE
        Single Runs (mode dégradé étiqueté) au lieu d'échouer. Le workflow réserve
        ce mode à la **dernière** tentative (après re-runs MF), pour privilégier la
        vraie prévi MF quand elle se rétablit.

    Returns
    -------
    int
        Code de retour (0 succès, 2 source, 3 SMTP / écriture, 4 composition).
    """
    if source is None:
        # Prévision officielle Météo-France roulante (ADR-0014) : un seul JSON
        # au point (picto orage + proba calibrée + T/pluie/vent), étiqueté par
        # sa fraîcheur (updated_on). Pas de run, pas d'ETP (cf. App 2).
        source = MeteoFranceOfficiel()
    if now_utc is None:
        now_utc = pd.Timestamp.now(tz="UTC")

    site = config["site"]
    tz_locale = site.get("tz", "Europe/Paris")
    logger.info(
        "Fetch prévision officielle MF lat=%.4f lon=%.4f",
        site["latitude"],
        site["longitude"],
    )
    repli_mf = False
    try:
        prevision = source.obtenir_prevision(
            latitude=site["latitude"],
            longitude=site["longitude"],
        )
    except (requests.HTTPError, PrevisionIndisponibleError) as e:
        logger.error("Prévision MF indisponible : %s", e)
        # Repli ARPEGE seulement à la dernière tentative (fallback_mf=True) ; sinon
        # on échoue (le workflow re-tente MF avant de basculer).
        prevision = (
            _prevision_repli_arpege(config, now_utc, source=semaine_source) if fallback_mf else None
        )
        if prevision is None:
            etape = (
                "fetch prévision MF (repli ARPEGE muet aussi)"
                if fallback_mf
                else "fetch prévision MF (muette)"
            )
            _envoyer_echec(config, secrets, now_utc, preview_path, etape, e)
            return 2
        repli_mf = True
        logger.warning("Repli 48 h sur ARPEGE Single Runs (webservice MF injoignable).")

    # Composition défensive : toute erreur inattendue → mail d'échec avec trace
    # (en plus de l'alerte GitHub) puis sortie code 4. La 48 h reste prioritaire.
    anomalies: list[Anomalie] = []
    if repli_mf:
        anomalies.append(
            Anomalie(
                "Prévision 48 h",
                "Prévision Météo-France indisponible, repli sur ARPEGE-Europe",
                "Webservice MF injoignable (timeout connexion depuis le runner) → 48 h "
                "reconstruit depuis ARPEGE Single Runs (Open-Meteo). Picto WMO ARPEGE, "
                "sans proba calibrée MF.",
            )
        )
    try:
        prevision_df = prevision.df
        ind = calculer_indicateurs(prevision_df, now_utc, config)
        alertes = evaluer_alertes(ind, config)
        logger.info("%d alerte(s) déclenchée(s)", len(alertes))

        # ADR-0014 : affichage tout en heure locale (fenêtre + périodes 6 h).
        chart = graphique_48h_base64(prevision_df, now_utc, tz_locale=tz_locale)
        # Grille Met Office + AROME (cartes synoptiques images). Cibles décalées
        # selon le moment d'envoi. Cartes manquantes sautées silencieusement.
        apres_midi = moment_envoi(now_utc, tz_locale) == "après-midi"
        cartes_grille = recuperer_cartes(now_utc=now_utc, apres_midi=apres_midi)
        # Vigilance MF (officielle d'État) — référence pour orages, vent, pluie,
        # canicule, neige-verglas, grand froid sur 0-48 h. Via le webservice
        # public (pas de clé) ; si injoignable, retourne None et le bloc est skippé.
        departement = str(config.get("vigilance_mf", {}).get("departement", "35"))
        vigilance = recuperer_vigilance(departement=departement)

        # Partie 2 « La semaine » — dans les DEUX créneaux. Le matin l'actualise ;
        # l'après-midi la rappelle à l'identique (``rappel=True`` → même run 00Z,
        # cohérent avec l'atelier qui fait une maj/jour). Cascade ARPEGE→ECMWF +
        # repli gracieux dans ``executer_semaine`` ; anomalies → rapport de bug.
        bloc_guides_tendance = ""
        bloc_sources_semaine = ""
        cartes_longue = None
        bloc_semaine_texte = ""
        if inclure_semaine:
            try:
                from apps.operationnelle.config import load_config as load_config_op

                config_op = load_config_op()
                atelier_url = config.get("email", {}).get("atelier_irrigation_url", "")
                resultat_semaine = executer_semaine(
                    config_op,
                    now_utc,
                    source=semaine_source,
                    fetch_cartes=fetch_cartes_semaine,
                    atelier_url=atelier_url,
                    rappel=apres_midi,
                )
            except Exception as e:  # noqa: BLE001 — la semaine ne casse jamais la 48 h
                logger.warning("Section semaine ignorée (erreur) : %s", e)
                resultat_semaine = None
                anomalies.append(
                    Anomalie(
                        "La semaine",
                        "Section semaine indisponible (erreur interne)",
                        f"{type(e).__name__}: {e}",
                    )
                )
            if resultat_semaine is not None:
                bloc_guides_tendance = resultat_semaine["guides_tendance_html"]
                bloc_sources_semaine = resultat_semaine["sources_html"]
                cartes_longue = resultat_semaine["cartes_geo"]
                bloc_semaine_texte = resultat_semaine["texte"]
                anomalies.extend(resultat_semaine.get("anomalies", []))
                logger.info("Section semaine ajoutée au mail matinal.")

        email = composer_email(
            ind,
            alertes,
            config,
            now_utc.to_pydatetime(),
            chart_48h_base64=chart,
            cartes_grille=cartes_grille,
            vigilance=vigilance,
            prevision_horaire=prevision_df,
            updated_on=prevision.updated_on,
            position=prevision.position,
            bloc_guides_tendance=bloc_guides_tendance,
            bloc_sources_semaine=bloc_sources_semaine,
            cartes_longue=cartes_longue,
            bloc_semaine_texte=bloc_semaine_texte,
            anomalies=anomalies,
            repli_mf=repli_mf,
        )
    except Exception as e:  # noqa: BLE001 — toujours notifier (mail d'échec + trace)
        logger.error("Composition du mail échouée : %s", e)
        _envoyer_echec(config, secrets, now_utc, preview_path, "composition du mail", e)
        return 4

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
    parser.add_argument(
        "--fallback-mf",
        action="store_true",
        help=(
            "Si la prévi MF est injoignable, replie le 48 h sur ARPEGE Single Runs "
            "(mode dégradé étiqueté) au lieu d'échouer. Réservé à la dernière "
            "tentative du workflow (après re-runs MF)."
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

    return executer_veille(config, secrets, preview_path=args.preview, fallback_mf=args.fallback_mf)


if __name__ == "__main__":
    sys.exit(main())
