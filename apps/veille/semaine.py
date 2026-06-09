"""Partie 2 « La semaine (7 j) » du mail — fusion de l'ancienne App 2.

Ce module compose la section *semaine* ajoutée à la suite du bloc 48 h du
mail matinal (cf. ``apps.veille.__main__``). Il reprend le contenu **statique**
de l'ancien dashboard Streamlit (App 2 Opérationnelle), désormais dissous :

- **Tendance jusqu'à 10 j** : ARPEGE (haut) + ECMWF IFS (bas) empilés par
  cellule, agrégés en fenêtres Nuit/Jour de 12 h **UTC** (calées sur les cycles
  de run), rendus en tables empilées par jour (mobile-first, comme la grille
  48 h — pas de table large à scroll horizontal qui passe mal en e-mail). ARPEGE
  s'arrête à J+4 (« — » au-delà), ECMWF va jusqu'à J+10.
- **Guides de décision de la semaine** : invitations à vérifier le terrain
  (``apps.operationnelle.decisions``). Seuils = config exploitation ; plus de
  sliders (le mail est statique).
- **Cartes ARPEGE-Europe** J+3/J+4 : récupérées ici mais **rendues avec le bloc
  synoptique 48 h** (Met Office + AROME + ARPEGE en une seule série), cf.
  ``apps.veille.email``.
- **Sources** : modèles, runs servis, proba d'ensemble, ETP socle (pied de mail).

Conventions (cf. mémoire ``feedback_libelle_utc`` / ``runs_deterministes_utc``) :
la partie 48 h reste en **heure locale** ; la partie semaine reste en **UTC**
(fenêtres calées sur les cycles), étiquetée explicitement. Un mail, deux
horloges assumées et labellisées.

Le bilan hydrique interactif (culture/sol/tunnel) **ne vit pas ici** : il est
extrait dans l'atelier irrigation (mini-Streamlit), lié en pied de section.

Dégradation gracieuse : toute la composition est défensive. Si le fetch des
Single Runs échoue, ``executer_semaine`` renvoie ``None`` et l'appelant livre le
mail 48 h sans la partie semaine (la 48 h stabilisée ne doit jamais casser).
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

from apps.operationnelle.cartes_geo import CartesGeoSerie
from apps.operationnelle.cartes_geo import recuperer_cartes as recuperer_cartes_geo
from apps.operationnelle.decisions import (
    THEMES_LIBELLES,
    GuideDecision,
    evaluer_decisions,
    grouper_par_theme,
    load_exploitation,
)
from apps.operationnelle.indicateurs import (
    calculer_indicateurs_quotidiens,
    jours_complets_seulement,
)
from apps.operationnelle.series_temp import etp_horaire_socle
from apps.operationnelle.tendances import (
    FENETRE_JOUR,
    FENETRE_NUIT,
    CelluleFenetre,
    agreger_par_fenetre,
)
from apps.shared.dates_fr import JOURS_FR
from meteo_socle.sources.openmeteo_runs import (
    ARPEGE,
    ECMWF,
    ECMWF_HRES,
    VARS_MONO_MODELE,
    OpenMeteoSingleRuns,
    creneau_run,
    runs_du_creneau,
)

logger = logging.getLogger(__name__)

# Palette Wong (cohérente avec le mail 48 h, cf. apps/veille/email.py).
_T_MOY = "#7f8c8d"
_T_MIN = "#0072B2"
_T_MAX = "#D55E00"
_PLUIE = "#56B4E9"
_PROBA = "#888888"
_VENT = "#009E73"
_RAFALES = "#E69F00"
_LABEL = "#34495e"

# URL de l'atelier irrigation (mini-Streamlit). Renseignée une fois l'app
# déployée ; vide → on n'affiche pas le lien (dégradé gracieux).
ATELIER_IRRIGATION_URL = ""

# Flèche pointant là où VA le vent (convention wind barbs, comme le mail 48 h).
_FLECHE_DIRECTION_VENT = {
    "N": "↓",
    "NE": "↙",
    "E": "←",
    "SE": "↖",
    "S": "↑",
    "SO": "↗",
    "O": "→",
    "NO": "↘",
}

# Largeurs fixes pour les tables tendance par jour (1 libellé + Nuit + Jour).
_GRILLE_COLGROUP = (
    '<colgroup><col style="width:34%"><col style="width:33%"><col style="width:33%"></colgroup>'
)


def _unite(texte: str) -> str:
    """Span unité discret (gris clair) à coller après une valeur."""
    return f'<span style="color:#aaa;font-weight:400;font-size:11px;">&nbsp;{texte}</span>'


def _date_fr_courte(d: pd.Timestamp) -> str:
    """``Lun. 02/06`` (jour capitalisé, abrégé 3 lettres + date)."""
    return f"{JOURS_FR[d.weekday()][:3].capitalize()}. {d.day:02d}/{d.month:02d}"


# --------------------------------------------------------------------------
# Formatteurs de cellule (CelluleFenetre → texte HTML), une valeur par modèle.
# --------------------------------------------------------------------------


def _fmt_t(cellule: CelluleFenetre, fenetre: str) -> str:
    if pd.isna(cellule.t_mean) or pd.isna(cellule.t_extreme):
        return "—"
    couleur_extreme = _T_MAX if fenetre == FENETRE_JOUR else _T_MIN
    return (
        f'<span style="color:{_T_MOY};">{cellule.t_mean:.0f}</span>'
        '<span style="color:#aaa;">/</span>'
        f'<span style="color:{couleur_extreme};">{cellule.t_extreme:.0f}</span>'
        f"{_unite('°C')}"
    )


def _fmt_pluie(cellule: CelluleFenetre, _fenetre: str) -> str:
    if pd.isna(cellule.pluie_mm):
        return "—"
    return f'<span style="color:{_PLUIE};">{cellule.pluie_mm:.1f}</span>' + _unite("mm")


def _fmt_proba(cellule: CelluleFenetre, _fenetre: str) -> str:
    if pd.isna(cellule.prob_pluie_pct):
        return "—"
    proba = int(round(cellule.prob_pluie_pct))
    return f'<span style="color:{_PROBA};">{proba:02d}</span>' + _unite("%")


def _fmt_vent(cellule: CelluleFenetre, _fenetre: str) -> str:
    if pd.isna(cellule.vent_moy_kmh) or pd.isna(cellule.rafales_max_kmh):
        return "—"
    return (
        f'<span style="color:{_VENT};">{cellule.vent_moy_kmh:.0f}</span>'
        '<span style="color:#aaa;">/</span>'
        f'<span style="color:{_RAFALES};">{cellule.rafales_max_kmh:.0f}</span>'
        f"{_unite('km/h')}"
    )


def _fmt_direction(cellule: CelluleFenetre, _fenetre: str) -> str:
    if not cellule.direction_cardinal:
        return "—"
    fleche = _FLECHE_DIRECTION_VENT.get(cellule.direction_cardinal, "·")
    return (
        f'<span style="font-size:18px;color:{_LABEL};line-height:1;">{fleche}</span>'
        f'<span style="color:#888;font-size:11px;">&nbsp;{cellule.direction_cardinal}</span>'
    )


def _fmt_etp(cellule: CelluleFenetre, _fenetre: str) -> str:
    if pd.isna(cellule.etp_mm):
        return "—"
    return f'<span style="color:{_LABEL};">{cellule.etp_mm:.1f}</span>' + _unite("mm")


# (libellé de ligne, formatteur). Ordre = ordre d'affichage dans chaque table.
_LIGNES_TENDANCE = (
    ("T° moy/extr", _fmt_t),
    ("Pluie", _fmt_pluie),
    ("Proba ≥1 mm/6 h", _fmt_proba),
    ("Vent moy/raf", _fmt_vent),
    ("Direction", _fmt_direction),
    ("ETP", _fmt_etp),
)


def _cellule_modeles(
    cell_a: CelluleFenetre | None,
    cell_e: CelluleFenetre | None,
    fenetre: str,
    formatteur,
    sep: str,
) -> str:
    """Cellule à 2 lignes : ARPEGE (haut) puis ECMWF IFS (bas, grisé).

    ``sep`` (bordure pleine) marque un **changement de variable** ; la ligne
    pointillée interne marque le **changement de modèle** — deux traits distincts
    pour ne pas confondre les deux.
    """
    val_a = formatteur(cell_a, fenetre) if cell_a is not None else "—"
    val_e = formatteur(cell_e, fenetre) if cell_e is not None else "—"
    return (
        '<td style="padding:3px 4px;text-align:center;font-size:13px;'
        "font-variant-numeric:tabular-nums;font-weight:700;"
        f'border-left:1px solid #eee;{sep}">'
        f"<div>{val_a}</div>"
        '<div style="opacity:0.6;border-top:1px dotted #e0e0e0;'
        f'margin-top:1px;padding-top:1px;">{val_e}</div>'
        "</td>"
    )


def _label_cellule(libelle: str, sep: str, avec_modeles: bool) -> str:
    """Cellule libellé de variable.

    Sur la 1ʳᵉ variable du 1ᵉʳ jour, rappelle quel modèle est sur quelle ligne
    (ARPEGE / ECMWF) aligné sur les 2 lignes de valeurs — évite une légende
    séparée (compacité demandée).
    """
    contenu = libelle
    if avec_modeles:
        contenu += (
            '<div style="font-weight:400;font-size:10px;color:#999;'
            'line-height:1.5;margin-top:2px;">ARPEGE<br>ECMWF</div>'
        )
    return (
        '<td style="padding:4px 8px;color:#555;font-size:13px;vertical-align:top;'
        f'{sep}">{contenu}</td>'
    )


def _table_jour(
    jour: pd.Timestamp,
    agg_arpege: dict[tuple[pd.Timestamp, str], CelluleFenetre],
    agg_ecmwf: dict[tuple[pd.Timestamp, str], CelluleFenetre],
    premier: bool,
) -> str:
    """Table compacte d'un jour : Nuit / Jour, lignes variables, 2 modèles empilés.

    Sur le **premier** jour seulement, les en-têtes de fenêtre portent leur plage
    horaire (UTC) et la 1ʳᵉ variable rappelle l'ordre des modèles — inutile de le
    répéter ensuite.
    """
    nuit_lbl = "Nuit (18–6 h)" if premier else "Nuit"
    jour_lbl = "Jour (6–18 h)" if premier else "Jour"
    en_tete = (
        '<tr style="background:#fafafa;">'
        '<th style="padding:6px 8px;text-align:left;color:#34495e;font-size:13px;">'
        f"{_date_fr_courte(jour)}</th>"
        '<th style="padding:6px 4px;text-align:center;font-size:11px;color:#888;'
        f'font-weight:400;">{nuit_lbl}</th>'
        '<th style="padding:6px 4px;text-align:center;font-size:11px;color:#888;'
        f'font-weight:400;">{jour_lbl}</th>'
        "</tr>"
    )
    lignes = [en_tete]
    for idx, (libelle, formatteur) in enumerate(_LIGNES_TENDANCE):
        # Séparateur de variable (bordure pleine) sur toutes sauf la première.
        sep = "" if idx == 0 else "border-top:1px solid #dcdcdc;"
        label = _label_cellule(libelle, sep, avec_modeles=(premier and idx == 0))
        cellules = "".join(
            _cellule_modeles(
                agg_arpege.get((jour, fenetre)),
                agg_ecmwf.get((jour, fenetre)),
                fenetre,
                formatteur,
                sep,
            )
            for fenetre in (FENETRE_NUIT, FENETRE_JOUR)
        )
        lignes.append("<tr>" + label + cellules + "</tr>")
    return (
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed;'
        'margin:8px 0;border:1px solid #eee;border-radius:4px;">'
        + _GRILLE_COLGROUP
        + "".join(lignes)
        + "</table>"
    )


def bloc_tendance(
    agg_arpege: dict[tuple[pd.Timestamp, str], CelluleFenetre],
    agg_ecmwf: dict[tuple[pd.Timestamp, str], CelluleFenetre],
    horizon_jours: int,
    jour_min: pd.Timestamp | None = None,
) -> str:
    """Bloc tendance — une table empilée par jour, 2 modèles par cellule.

    ARPEGE (haut) et ECMWF IFS (bas) côte à côte tant qu'ils se recouvrent ;
    « — » au-delà de l'horizon d'un modèle (ARPEGE ≤ J+4, ECMWF jusqu'à J+10).

    ``jour_min`` (minuit UTC d'aujourd'hui) écarte le bout de passé que traîne le
    run ECMWF du créneau (12Z J-1) : la tendance démarre aujourd'hui.
    """
    jours = sorted({jour for (jour, _f) in {**agg_arpege, **agg_ecmwf}})
    if jour_min is not None:
        jours = [j for j in jours if j >= jour_min]
    jours = jours[:horizon_jours]
    if not jours:
        return ""
    tables = "".join(
        _table_jour(jour, agg_arpege, agg_ecmwf, premier=(i == 0)) for i, jour in enumerate(jours)
    )
    return (
        '<h3 style="margin:14px 0 4px 0;font-size:15px;color:#34495e;">'
        f"Tendance jusqu'à {horizon_jours} jours</h3>" + tables
    )


# --------------------------------------------------------------------------
# Guides de décision (rendu HTML statique, seuils config).
# --------------------------------------------------------------------------

_COULEUR_NIVEAU = {"critique": "#D55E00", "anticiper": "#E69F00", "info": "#7f8c8d"}


def _rendre_guide(guide: GuideDecision) -> str:
    """Un guide : titre coloré par niveau (actif) ou grisé (inactif)."""
    if guide.active:
        couleur = _COULEUR_NIVEAU.get(guide.niveau, "#7f8c8d")
        opacite = "1.0"
        poids = "700"
    else:
        couleur = "#9aa3a8"
        opacite = "0.7"
        poids = "400"
    return (
        f'<div style="margin:6px 0;padding:8px 12px;border-left:4px solid {couleur};'
        f'background:#fbfbfb;border-radius:0 4px 4px 0;opacity:{opacite};">'
        f'<span style="font-size:18px;line-height:1;">{guide.picto}</span>'
        f'<span style="font-size:14px;font-weight:{poids};color:{couleur};margin-left:6px;">'
        f"{guide.titre}</span>"
        "</div>"
    )


def bloc_guides(guides: list[GuideDecision]) -> str:
    """Guides de décision groupés par thème (actifs mis en avant, inactifs grisés)."""
    titre = (
        '<h3 style="margin:16px 0 6px 0;font-size:15px;color:#34495e;">'
        "Guides de décision de la semaine</h3>"
        '<p style="margin:0 0 6px 0;font-size:11px;color:#888;line-height:1.4;">'
        "Invitations à vérifier sur le terrain, motivées par la prévision 7 j. "
        "Seuils par défaut de l'exploitation.</p>"
    )
    if not guides:
        return (
            titre + '<div style="padding:8px 12px;background:#f4f4f4;border-radius:4px;'
            'font-size:12px;color:#555;">Aucun guide applicable cette semaine '
            "(hors saison ou données insuffisantes).</div>"
        )
    sections: list[str] = []
    for theme, guides_theme in grouper_par_theme(guides):
        sections.append(
            '<h4 style="margin:12px 0 4px 0;font-size:13px;color:#34495e;'
            'border-bottom:1px solid #eee;padding-bottom:3px;">'
            f"{THEMES_LIBELLES[theme]}</h4>" + "".join(_rendre_guide(g) for g in guides_theme)
        )
    return titre + "".join(sections)


# --------------------------------------------------------------------------
# Cartes géo ARPEGE-Europe (J+1 → J+4).
# --------------------------------------------------------------------------


def bloc_sources_semaine(
    horizon_court: int,
    horizon_long: int,
    run_arpege: pd.Timestamp,
    run_ecmwf: pd.Timestamp,
) -> str:
    """Pied de section semaine — transparence sur modèles, runs, méthode."""

    def _run(ts: pd.Timestamp) -> str:
        return ts.strftime("%d/%m %HZ")

    lignes = [
        f"<strong>ARPEGE</strong> Météo-France ~10 km — court terme "
        f"(0-{horizon_court} j), guides + tendance · run {_run(run_arpege)}.",
        f"<strong>ECMWF IFS</strong> ~9 km — tendance longue (0-{horizon_long} j) "
        f"· run {_run(run_ecmwf)}.",
        "<strong>Proba pluie</strong> : % de membres ECMWF IFS-ENS au cumul ≥ 1 mm/6 h "
        "(dernier run d'ensemble).",
        "<strong>ETP</strong> : socle FAO Penman-Monteith (pas le champ du fournisseur).",
        "Single Runs Open-Meteo, runs explicites, raisonnement tout-UTC.",
    ]
    items = "".join(f'<div style="margin:2px 0;">{ligne}</div>' for ligne in lignes)
    return (
        '<div style="margin-top:12px;padding-top:12px;border-top:1px solid #eee;'
        'font-size:11px;color:#888;line-height:1.5;">'
        '<div style="font-weight:600;color:#555;margin-bottom:4px;">'
        "Sources — semaine</div>" + items + "</div>"
    )


def _bloc_lien_atelier() -> str:
    """Lien vers l'atelier irrigation (bilan hydrique interactif), si configuré."""
    if not ATELIER_IRRIGATION_URL:
        return ""
    return (
        '<div style="margin:14px 0 0 0;padding:10px 12px;background:#f0f6f4;'
        'border-radius:4px;font-size:12px;color:#34495e;">'
        "💧 Pour explorer le bilan hydrique (culture, sol, tunnel) jour par jour : "
        f'<a href="{ATELIER_IRRIGATION_URL}" style="color:#009E73;font-weight:600;">'
        "atelier irrigation</a>.</div>"
    )


def composer_guides_tendance(
    agg_arpege: dict[tuple[pd.Timestamp, str], CelluleFenetre],
    agg_ecmwf: dict[tuple[pd.Timestamp, str], CelluleFenetre],
    guides: list[GuideDecision],
    horizon_long: int,
    jour_min: pd.Timestamp | None = None,
) -> str:
    """Bloc « La semaine » : guides + tendance (les cartes sont regroupées avec le
    bloc synoptique 48 h, plus bas dans le mail ; cf. ``email.py``)."""
    return (
        '<h2 style="margin:24px 0 8px 0;font-size:17px;color:#2c3e50;'
        'border-bottom:2px solid #2c3e50;padding-bottom:4px;">'
        "La semaine</h2>"
        '<p style="margin:0 0 8px 0;font-size:12px;color:#888;">'
        "Tendance et anticipation à moyen terme — horaires en <strong>UTC</strong> "
        "(la partie 48 h ci-dessus est en heure locale).</p>"
        + bloc_guides(guides)
        + bloc_tendance(agg_arpege, agg_ecmwf, horizon_long, jour_min=jour_min)
        + _bloc_lien_atelier()
    )


def composer_section_semaine_texte(guides: list[GuideDecision]) -> str:
    """Équivalent texte (fallback) — les guides en mots, l'essentiel actionnable."""
    lignes = ["", "=" * 70, "LA SEMAINE (7 j) — horaires UTC", ""]
    lignes.append("GUIDES DE DÉCISION :")
    if not guides:
        lignes.append("  Aucun guide applicable cette semaine.")
    else:
        for theme, guides_theme in grouper_par_theme(guides):
            lignes.append(f"  [{THEMES_LIBELLES[theme]}]")
            for g in guides_theme:
                marque = "→" if g.active else " "
                lignes.append(f"   {marque} {g.titre}")
    return "\n".join(lignes)


# --------------------------------------------------------------------------
# Orchestration : fetch Single Runs + agrégation + rendu.
# --------------------------------------------------------------------------


def executer_semaine(
    config_op: dict[str, Any],
    now_utc: pd.Timestamp,
    source: OpenMeteoSingleRuns | None = None,
    exploitation: dict[str, Any] | None = None,
    cartes_geo: CartesGeoSerie | None = None,
    fetch_cartes: bool = True,
) -> dict[str, Any] | None:
    """Construit les éléments de la section semaine, ou ``None`` en cas d'échec.

    Renvoie un dict :

    - ``guides_tendance_html`` : bloc « La semaine » (guides + tendance) ;
    - ``cartes_geo`` : ``CartesGeoSerie`` ARPEGE J+3/J+4 (regroupée avec le bloc
      synoptique 48 h par ``email.py``), ou ``None`` ;
    - ``sources_html`` : pied « Sources — semaine » (placé en bas du mail) ;
    - ``texte`` : équivalent texte (fallback).


    Forward-only (pas de passé stitché) : le mail matin est tourné vers
    l'anticipation. Les deux modèles sont servis par leur run du créneau
    courant (table déterministe ADR-0011). Toute exception est capturée et
    journalisée → ``None`` (l'appelant livre alors le mail 48 h seul).

    Parameters
    ----------
    config_op :
        Config App 2 (``site`` + ``source_meteo`` requis).
    now_utc :
        Référence temporelle (tz-aware UTC).
    source :
        Client Single Runs injectable (tests). Défaut : ``OpenMeteoSingleRuns()``.
    exploitation :
        Config exploitation (guides). Défaut : ``load_exploitation()``.
    cartes_geo :
        Série de cartes injectable (tests). Si ``None`` et ``fetch_cartes``,
        récupérée en ligne ; sinon omise.
    fetch_cartes :
        Mettre ``False`` pour ne pas tenter le fetch réseau des cartes.
    """
    try:
        if source is None:
            source = OpenMeteoSingleRuns()
        if exploitation is None:
            exploitation = load_exploitation()

        site = config_op["site"]
        sm = config_op["source_meteo"]
        horizon_court = int(sm["horizon_court_jours"])
        horizon_long = int(sm["horizon_long_jours"])
        lat = site["latitude"]
        lon = site["longitude"]

        creneau, jour = creneau_run(now_utc)
        runs = runs_du_creneau(creneau, jour)
        run_arpege = runs[ARPEGE]
        run_ecmwf = runs[ECMWF_HRES]

        df_arpege = source.obtenir_run(
            ARPEGE, run_arpege, lat, lon, horizon_court, VARS_MONO_MODELE
        )
        df_ecmwf = source.obtenir_run(ECMWF, run_ecmwf, lat, lon, horizon_long, VARS_MONO_MODELE)
        if df_arpege is None or df_arpege.empty:
            logger.warning("Semaine : run ARPEGE %s muet — section omise", run_arpege)
            return None
        if df_ecmwf is None or df_ecmwf.empty:
            logger.warning("Semaine : run ECMWF %s muet — section omise", run_ecmwf)
            return None

        # Proba d'ensemble ECMWF IFS-ENS (dégradation gracieuse si muette).
        try:
            proba = source.obtenir_proba_ensemble(lat, lon, horizon_long, past_days=0)
            if proba is not None:
                df_ecmwf = df_ecmwf.copy()
                df_ecmwf["probabilite_pluie_pct"] = proba.reindex(df_ecmwf.index)
        except requests.RequestException as e:
            logger.warning("Semaine : proba d'ensemble indisponible (omise) : %s", e)

        etp_arpege = etp_horaire_socle(df_arpege, site)
        etp_ecmwf = etp_horaire_socle(df_ecmwf, site)
        agg_arpege = agreger_par_fenetre(df_arpege, "UTC", horizon_long, etp_arpege)
        agg_ecmwf = agreger_par_fenetre(df_ecmwf, "UTC", horizon_long, etp_ecmwf)

        # Guides : indicateurs quotidiens ARPEGE (jours complets uniquement).
        quotidien = calculer_indicateurs_quotidiens(df_arpege, config_op, now_utc=now_utc)
        quotidien = jours_complets_seulement(quotidien, df_arpege)
        tz_site = site.get("tz", "Europe/Paris")
        today_local = now_utc.tz_convert(tz_site).normalize().tz_localize(None)
        guides = evaluer_decisions(quotidien, exploitation, today_local)

        if cartes_geo is None and fetch_cartes:
            try:
                # Prolongement des cartes synoptiques 48 h : seulement J+3 / J+4
                # (T+72 / T+96, horizon natif d'ARPEGE-Europe), à 00Z. Résolution
                # réduite (520 px) pour limiter le poids, emprise pleine largeur.
                cartes_geo = recuperer_cartes_geo(
                    now_utc=now_utc, echeances=(72, 96), largeur_max_px=520
                )
            except (requests.RequestException, OSError) as e:
                logger.warning("Semaine : cartes ARPEGE-Europe indisponibles (omises) : %s", e)
                cartes_geo = None

        return {
            "guides_tendance_html": composer_guides_tendance(
                agg_arpege, agg_ecmwf, guides, horizon_long, jour_min=now_utc.normalize()
            ),
            "cartes_geo": cartes_geo,
            "sources_html": bloc_sources_semaine(
                horizon_court, horizon_long, run_arpege, run_ecmwf
            ),
            "texte": composer_section_semaine_texte(guides),
        }
    except Exception as e:  # noqa: BLE001 — la semaine ne doit jamais casser la 48 h
        logger.error("Semaine : composition échouée (section omise) : %s", e)
        return None
