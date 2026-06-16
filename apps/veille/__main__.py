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

from meteo_socle.sources.dpvigilance import (
    VigilanceDPIndisponibleError,
    recuperer_vigilance_dp,
)
from meteo_socle.sources.meteofrance_arome import AromeIndisponibleError
from meteo_socle.sources.meteofrance_officiel import (
    MeteoFranceOfficiel,
    PrevisionIndisponibleError,
)
from meteo_socle.sources.meteofrance_proba_arome import ProbaAromeIndisponibleError
from meteo_socle.sources.meteofrance_vigilance import recuperer_vigilance

from .alertes import evaluer_alertes
from .anomalies import Anomalie
from .cartes_synoptiques import recuperer_cartes
from .config import (
    ConfigError,
    load_config,
    load_dotenv_if_present,
    load_smtp_secrets,
)
from .email import composer_email, composer_email_echec
from .indicateurs import calculer_indicateurs, moment_envoi
from .prevision_48h import assembler_prevision_48h
from .semaine import executer_semaine
from .sender import envoyer

logger = logging.getLogger(__name__)

# Sélection de run portail-api (ADR-0021) : déterministe (constantes corrigeables,
# cf. principe runs-déterministes). On prend le **run le plus récent publié** (âge ≥
# latence), sur la **grille horaire propre à chaque modèle** — pas un floor après
# soustraction (qui saute un cycle). Heures de run UTC : AROME HD = 00/03/.../21
# (cycle 3 h, offset 0) ; PE-AROME = 03/09/15/21 (cycle 6 h, **offset 3**, vérifié
# 2026-06-16 : run 15 Z, pas 12 Z). Latence min ~3,5 h (run 15 Z dispo à 19 h 30 =
# 4,5 h ; 18 Z absent à 1,5 h) — à affiner si un run choisi 404 (→ 48 h omise, retry).
LATENCE_MIN_PORTAIL_H = 3.5
CYCLE_AROME_H, OFFSET_AROME_H = 3, 0
CYCLE_PEAROME_H, OFFSET_PEAROME_H = 6, 3
# Erreurs « 48 h indisponible » (webservice OU portail-api) → même repli (omission).
_ERREURS_48H = (
    requests.RequestException,
    PrevisionIndisponibleError,
    AromeIndisponibleError,
    ProbaAromeIndisponibleError,
    VigilanceDPIndisponibleError,
)


def _run_recent(
    now_utc: pd.Timestamp,
    cycle_h: int,
    offset_h: int,
    latence_min_h: float = LATENCE_MIN_PORTAIL_H,
) -> pd.Timestamp:
    """Run UTC le plus récent (heure ≡ ``offset`` mod ``cycle``) d'âge ≥ ``latence``.

    Descend par pas de 1 h jusqu'à une heure de run valide du modèle, puis par pas de
    ``cycle`` jusqu'à un run assez vieux pour être publié. Évite le ``floor`` après
    soustraction, qui sautait un cycle (run inutilement vieux) — et respecte la grille
    décalée de PE-AROME (03/09/15/21).
    """
    c = now_utc.floor("h")
    while (c.hour - offset_h) % cycle_h != 0:
        c -= pd.Timedelta(hours=1)
    while now_utc - c < pd.Timedelta(hours=latence_min_h):
        c -= pd.Timedelta(hours=cycle_h)
    return c


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
    source_arpege_mf: Any = None,
    source_ecmwf_opendata: Any = None,
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
        Si ``True`` et que la prévi MF reste injoignable, **omet la partie 48 h**
        (au lieu d'échouer) et envoie le mail avec la seule section « La semaine »
        (tendance 0-10 j ARPEGE/ECMWF), qui porte l'essentiel. On n'invente plus de
        repli 48 h. Le workflow réserve ce mode à la **dernière** tentative (après
        re-runs MF), pour privilégier la vraie prévi MF quand elle se rétablit.

    Returns
    -------
    int
        Code de retour (0 succès, 2 source, 3 SMTP / écriture, 4 composition).
    """
    if now_utc is None:
        now_utc = pd.Timestamp.now(tz="UTC")
    site = config["site"]
    tz_locale = site.get("tz", "Europe/Paris")
    departement = str(config.get("vigilance_mf", {}).get("departement", "35"))
    # Source 48 h : webservice MF (roulant, ADR-0014) OU portail-api direct (AROME +
    # PE-AROME + DPVigilance, ADR-0021) selon le flag. ``source`` injectée (tests) →
    # webservice. Flag OFF par défaut → bascule live progressive.
    portail = source is None and bool(
        config.get("source_meteo", {}).get("veille_portail_api", False)
    )
    if source is None and not portail:
        source = MeteoFranceOfficiel()
    logger.info(
        "Fetch prévision 48 h (%s) lat=%.4f lon=%.4f",
        "portail-api" if portail else "webservice MF",
        site["latitude"],
        site["longitude"],
    )
    mf_indispo = False
    mf_exc: BaseException | None = None
    vigilance_pre = None  # Vigilance fetchée avec la 48 h (chemin portail) ou None.
    try:
        if portail:
            run_a = _run_recent(now_utc, CYCLE_AROME_H, OFFSET_AROME_H)
            run_p = _run_recent(now_utc, CYCLE_PEAROME_H, OFFSET_PEAROME_H)
            pos = {"name": site.get("localisation", ""), "timezone": tz_locale}
            # Cache parquet du run AROME (le fetch 48 h horaire est ~500 requêtes WCS).
            cache_arome = config.get("source_meteo", {}).get("arome_cache_dir")
            # Repli run précédent : si le run le plus frais n'est pas ENCORE publié
            # (404 rapide au matin, latence > estimée), on retente une fois sur le cycle
            # d'avant plutôt que d'omettre la 48 h.
            for essai in range(2):
                try:
                    prevision, vigilance_pre = assembler_prevision_48h(
                        run_a,
                        site["latitude"],
                        site["longitude"],
                        departement=departement,
                        position=pos,
                        run_proba_utc=run_p,
                        cache_dir=cache_arome,
                    )
                    break
                except (AromeIndisponibleError, ProbaAromeIndisponibleError) as e:
                    if essai == 1:
                        raise
                    logger.warning(
                        "Run portail (AROME %s) indisponible (%s) → repli run précédent.",
                        f"{run_a:%Y-%m-%dT%HZ}",
                        e,
                    )
                    run_a -= pd.Timedelta(hours=CYCLE_AROME_H)
                    run_p -= pd.Timedelta(hours=CYCLE_PEAROME_H)
        else:
            prevision = source.obtenir_prevision(
                latitude=site["latitude"],
                longitude=site["longitude"],
            )
    except _ERREURS_48H as e:
        logger.error("Prévision 48 h indisponible : %s", e)
        if not fallback_mf:
            # Tentative intermédiaire : 48 h injoignable (webservice bloqué depuis les
            # runners, ou portail en erreur). PAS de mail d'échec — le workflow retente
            # puis bascule en dernier recours (fallback_mf), qui envoie SANS la 48 h.
            logger.warning("48 h injoignable (essai intermédiaire) — pas d'échec mailé, retry.")
            return 2
        # Dernier recours : on n'invente PLUS de 48 h → on OMET la partie 48 h et on
        # livre le mail « La semaine » seule (omission tracée au rapport de bug).
        logger.warning("48 h injoignable au dernier essai → mail sans la partie 48 h.")
        prevision = None
        mf_indispo = True
        mf_exc = e

    # Composition défensive : toute erreur inattendue → mail d'échec avec trace
    # (en plus de l'alerte GitHub) puis sortie code 4.
    anomalies: list[Anomalie] = []
    if mf_indispo:
        anomalies.append(
            Anomalie(
                "Prévision 48 h",
                "Prévision Météo-France indisponible — partie 48 h omise",
                "Webservice MF injoignable (timeout connexion depuis le runner). La "
                "partie 48 h (prévision officielle MF) est omise ; la tendance des "
                "prochains jours ci-dessous (ARPEGE/ECMWF) porte l'essentiel.",
            )
        )
    try:
        if prevision is not None:
            prevision_df = prevision.df
            ind = calculer_indicateurs(prevision_df, now_utc, config)
            alertes = evaluer_alertes(ind, config)
            logger.info("%d alerte(s) déclenchée(s)", len(alertes))
        else:
            # 48 h omise : pas d'indicateurs ni d'alertes exploitation (la Vigilance
            # d'État, elle, reste tentée plus bas — fetch indépendant).
            prevision_df = None
            ind = None
            alertes = []

        # Grille Met Office + AROME (cartes synoptiques images). Cibles décalées
        # selon le moment d'envoi. Cartes manquantes sautées silencieusement.
        apres_midi = moment_envoi(now_utc, tz_locale) == "après-midi"
        cartes_grille = recuperer_cartes(now_utc=now_utc, apres_midi=apres_midi)
        # Vigilance MF (officielle d'État) — référence pour orages, vent, pluie,
        # canicule, neige-verglas, grand froid sur 0-48 h. Chemin portail : déjà
        # fetchée avec la 48 h (DPVigilance, horodatée) ; sinon webservice public.
        # Injoignable → None et le bloc est skippé.
        if portail:
            vigilance = vigilance_pre
            if vigilance is None:  # 48 h portail échouée → Vigilance seule, best-effort.
                try:
                    vigilance = recuperer_vigilance_dp(departement=departement)
                except VigilanceDPIndisponibleError:
                    vigilance = None
        else:
            vigilance = recuperer_vigilance(departement=departement)

        # Partie 2 « La semaine » — dans les DEUX créneaux. Le matin l'actualise ;
        # l'après-midi la rappelle à l'identique (``rappel=True`` → même run 00Z,
        # cohérent avec l'atelier qui fait une maj/jour). Cascade ARPEGE→ECMWF +
        # repli gracieux dans ``executer_semaine`` ; anomalies → rapport de bug.
        bloc_guides_tendance = ""
        bloc_sources_semaine = ""
        cartes_longue = None
        bloc_semaine_texte = ""
        resultat_semaine: dict[str, Any] | None = None
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
                    source_arpege_mf=source_arpege_mf,
                    source_ecmwf_opendata=source_ecmwf_opendata,
                    # Proba pluie de la semaine = proba officielle MF calibrée, déjà
                    # récupérée ici (signal autonome ~J+10). None si MF injoignable
                    # (48 h omise) → pas de proba (dégradation gracieuse).
                    proba_mf=prevision.proba_bins if prevision is not None else None,
                    # 48 h omise → l'intro semaine ne renvoie pas à une section absente.
                    avec_48h=not mf_indispo,
                    # Picto semaine unifié (moteur diagnostic) en même temps que la 48 h
                    # portail-api (ADR-0021) ; OFF → picto nébulosité+pluie historique.
                    picto_diagnostic=portail,
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

        # Dernier recours sans contenu : MF injoignable (48 h omise) ET la semaine
        # vide (les deux modèles muets ou erreur) → rien d'utile à envoyer → vrai
        # échec (mail de debug). On ne livre jamais un mail vide (jamais_fausses_valeurs).
        if mf_indispo and (resultat_semaine is None or resultat_semaine.get("vide", False)):
            assert mf_exc is not None
            _envoyer_echec(
                config,
                secrets,
                now_utc,
                preview_path,
                "fetch prévision MF (semaine aussi indisponible)",
                mf_exc,
            )
            return 2

        email = composer_email(
            ind,
            alertes,
            config,
            now_utc.to_pydatetime(),
            cartes_grille=cartes_grille,
            vigilance=vigilance,
            prevision_horaire=prevision_df,
            updated_on=prevision.updated_on if prevision is not None else None,
            position=prevision.position if prevision is not None else None,
            bloc_guides_tendance=bloc_guides_tendance,
            bloc_sources_semaine=bloc_sources_semaine,
            cartes_longue=cartes_longue,
            bloc_semaine_texte=bloc_semaine_texte,
            anomalies=anomalies,
            # Portail-api : la 48 h est le modèle AROME (picto dérivé), pas la prévi
            # officielle post-traitée → étiquetage honnête (ADR-0021).
            prevision_officielle=not portail,
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
            "Si la prévi 48 h reste injoignable, OMET la partie 48 h (mail « La "
            "semaine » seule) au lieu d'échouer. Réservé à la dernière tentative du "
            "workflow (après re-runs)."
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
