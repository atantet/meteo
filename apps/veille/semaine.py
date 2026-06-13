"""Partie 2 « La semaine (7 j) » du mail — fusion de l'ancienne App 2.

Ce module compose la section *semaine* ajoutée à la suite du bloc 48 h du
mail matinal (cf. ``apps.veille.__main__``). Il reprend le contenu **statique**
de l'ancien dashboard Streamlit (App 2 Opérationnelle), désormais dissous :

- **Tendance jusqu'à 10 j** : ARPEGE (haut) + ECMWF IFS (bas) empilés par
  cellule, agrégés en fenêtres Nuit/Jour de 12 h **UTC** (calées sur les cycles
  de run), rendus en tables empilées par jour (mobile-first, comme la grille
  48 h — pas de table large à scroll horizontal qui passe mal en e-mail). ARPEGE
  s'arrête à J+4 ; au-delà, une seule ligne ECMWF (jusqu'à J+10), sans ligne
  ARPEGE vide.
- **Guides de décision de la semaine** : invitations à vérifier le terrain
  (``apps.operationnelle.decisions``). Seuils = config exploitation ; plus de
  sliders (le mail est statique).
- **Cartes ARPEGE-Europe** J+3/J+4 : récupérées ici mais **rendues avec le bloc
  synoptique 48 h** (Met Office + AROME + ARPEGE en une seule série), cf.
  ``apps.veille.email``.
- **Proba pluie** : proba officielle MF calibrée (signal autonome, ni ARPEGE ni
  ECMWF), affichée en tête de cellule ; déjà récupérée par App 1.
- **Sources** : modèles, runs servis, proba MF, ETP socle (pied de mail).

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

import base64
import io
import logging
import re
from typing import Any

import numpy as np
import pandas as pd
import requests
from matplotlib.figure import Figure  # API sans pyplot/backend GUI (sûr en headless)

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
    proba_max_par_fenetre,
)
from apps.shared.dates_fr import JOURS_FR
from apps.shared.pictograms import icone_base64, libelle
from apps.veille.anomalies import Anomalie, note_inline
from meteo_socle.sources.openmeteo_runs import (
    ARPEGE,
    ECMWF,
    ECMWF_HRES,
    VARS_MONO_MODELE,
    OpenMeteoSingleRuns,
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


def _code_wmo(nebulosite_pct: float, pluie_mm: float) -> int | None:
    """Code WMO dérivé d'ARPEGE (nébulosité octas + cumul pluie doctrine).

    Seuils pluie (config) : 1-5 légère, 5-20 modérée, > 20 forte. En l'absence de
    pluie, le ciel vient des octas OMM : ≤ 2/8 clair, 3-5/8 partiellement nuageux,
    ≥ 6/8 couvert. ``None`` si on ne peut rien déduire (nébulosité absente, sec).
    """
    if not pd.isna(pluie_mm) and pluie_mm >= 1.0:
        if pluie_mm < 5:
            return 61  # pluie légère
        if pluie_mm < 20:
            return 63  # pluie modérée
        return 65  # pluie forte
    if pd.isna(nebulosite_pct):
        return None
    oktas = nebulosite_pct / 100.0 * 8.0
    if oktas <= 2:
        return 0  # clair
    if oktas < 6:
        return 2  # partiellement nuageux
    return 3  # couvert


def _fmt_ciel(cellule: CelluleFenetre, fenetre: str) -> str:
    """Cellule ciel : **proba | picto ciel | flèche ETP** (picto ciel centré).

    Le picto ciel (icône yr dérivée d'ARPEGE : octas + pluie) est au centre ; la
    proba (MF officielle, signal autonome) est à gauche, la flèche ETP à droite —
    slots latéraux de largeur égale pour que le ciel reste aligné entre les
    lignes ARPEGE et ECMWF.
    """
    code = _code_wmo(cellule.nebulosite_pct, cellule.pluie_mm)
    if code is None:
        return "—"
    nuit = fenetre == FENETRE_NUIT
    lib = libelle(code)
    ciel = (
        f'<img src="{icone_base64(code, nuit=nuit)}" width="34" height="34" '
        f'alt="{lib}" title="{lib}" style="vertical-align:bottom;">'
    )
    proba = "" if pd.isna(cellule.prob_pluie_pct) else f"{int(round(cellule.prob_pluie_pct)):02d}%"
    etp = _etp_arrow_html(cellule.etp_mm)
    return (
        '<table role="presentation" style="margin:0 auto;border-collapse:collapse;"><tr>'
        f'<td style="width:38px;text-align:right;vertical-align:bottom;font-size:10px;'
        f'color:{_PROBA};">{proba}</td>'
        f'<td style="text-align:center;vertical-align:bottom;">{ciel}</td>'
        f'<td style="width:38px;text-align:left;vertical-align:bottom;">{etp}</td>'
        "</tr></table>"
    )


def _fmt_vent_combine(cellule: CelluleFenetre, _fenetre: str) -> str:
    """Vent moyen / rafales (km/h) + flèche de direction, sur une ligne.

    Ne **jamais cacher une donnée disponible** : on affiche le vent moyen + la
    direction dès que la moyenne existe ; si la **rafale** manque (trou
    d'ingestion fournisseur — fréquent côté ECMWF en moyenne portée), on la
    remplace par « – » plutôt que de masquer toute la cellule. « — » complet
    seulement si le vent moyen lui-même manque.
    """
    if pd.isna(cellule.vent_moy_kmh):
        return "—"
    raf = (
        '<span style="color:#bbb;">–</span>'
        if pd.isna(cellule.rafales_max_kmh)
        else f'<span style="color:{_RAFALES};">{cellule.rafales_max_kmh:.0f}</span>'
    )
    vent = (
        f'<span style="color:{_VENT};">{cellule.vent_moy_kmh:.0f}</span>'
        '<span style="color:#aaa;">/</span>'
        f"{raf}"
        f"{_unite('km/h')}"
    )
    if not cellule.direction_cardinal:
        return vent
    fleche = _FLECHE_DIRECTION_VENT.get(cellule.direction_cardinal, "·")
    return vent + (
        f'<span style="color:{_LABEL};font-size:19px;font-weight:700;'
        f'line-height:1;">&nbsp;{fleche}</span>'
    )


# Flèche(s) ETP (PNG généré, sûr en e-mail) ; cache par (couleur, nombre).
_FLECHE_ETP_CACHE: dict[tuple[str, int], str] = {}


def _fleche_etp_png(color: str, n: int) -> str:
    """``n`` flèches d'évaporation côte à côte, colorées — PNG base64 (cache).

    Chaque flèche : queue ondulée (revient au centre en haut) → tige droite →
    pointe bien visible, centrée et rectiligne.
    """
    key = (color, n)
    if key in _FLECHE_ETP_CACHE:
        return _FLECHE_ETP_CACHE[key]
    fig = Figure(figsize=(0.30 * n + 0.08, 0.6))
    ax = fig.add_subplot()
    for i in range(n):
        cx = float(i)
        y_w = np.linspace(0.0, 0.52, 50)
        x_w = cx + 0.13 * np.sin(y_w / 0.52 * 2 * np.pi)
        ax.plot(x_w, y_w, color=color, linewidth=2.4, solid_capstyle="round")
        ax.plot([cx, cx], [0.52, 0.80], color=color, linewidth=2.4, solid_capstyle="round")
        ax.annotate(
            "",
            xy=(cx, 1.04),
            xytext=(cx, 0.80),
            arrowprops={"arrowstyle": "-|>", "color": color, "lw": 2.4, "mutation_scale": 13},
        )
    ax.set_xlim(-0.4, (n - 1) + 0.4)
    ax.set_ylim(-0.05, 1.12)
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight", pad_inches=0.02)
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    _FLECHE_ETP_CACHE[key] = uri
    return uri


def _etp_arrow_html(etp: float) -> str:
    """Indicateur ETP doublé (couleur + nombre de flèches) ; ``~`` gris sous le seuil.

    Paliers fixes : 1-2 mm → 1 flèche jaune · 2-3 → 2 orange · > 3 → 3 rouges.
    Sous 1 mm (ou ETP absente) → ``~`` gris discret (placeholder).
    """
    if pd.isna(etp) or etp < 1.0:
        return '<span style="color:#bbb;font-size:14px;">~</span>'
    if etp < 2.0:
        color, n = "#E6B800", 1  # jaune
    elif etp < 3.0:
        color, n = "#E67E00", 2  # orange
    else:
        color, n = "#D11500", 3  # rouge
    uri = _fleche_etp_png(color, n)
    return (
        f'<img src="{uri}" alt="ETP {etp:.1f} mm" title="ETP {etp:.1f} mm" '
        'style="height:20px;vertical-align:bottom;">'
    )


# (libellé de ligne, formatteur). Le picto « Ciel » (dérivé d'ARPEGE) absorbe
# nébulosité + pluie, avec la proba (MF officielle) à gauche et la flèche ETP à droite.
_LIGNES_TENDANCE = (
    ("Ciel", _fmt_ciel),
    ("T° moy/extr", _fmt_t),
    ("Vent · dir", _fmt_vent_combine),
)


def _cellule_modeles(
    cell_a: CelluleFenetre | None,
    cell_e: CelluleFenetre | None,
    fenetre: str,
    formatteur,
    sep: str,
    ecmwf_seul: bool,
) -> str:
    """Cellule de tendance.

    - Jour couvert par ARPEGE : 2 lignes — ARPEGE (haut) puis ECMWF IFS (bas) ;
      la ligne pointillée interne marque le changement de modèle.
    - Jour ECMWF seul (au-delà de l'horizon ARPEGE) : une seule ligne (ECMWF),
      sans ligne ARPEGE vide.

    Les deux lignes sont en pleine couleur (le label ARPEGE/ECMWF et le pointillé
    suffisent à les distinguer). ``sep`` (bordure pleine) = changement de variable.
    """
    val_e = formatteur(cell_e, fenetre) if cell_e is not None else "—"
    td_ouvrant = (
        '<td style="padding:3px 4px;text-align:center;font-size:13px;'
        "font-variant-numeric:tabular-nums;font-weight:700;"
        f'border-left:1px solid #eee;{sep}">'
    )
    if ecmwf_seul:
        return td_ouvrant + f"<div>{val_e}</div></td>"
    val_a = formatteur(cell_a, fenetre) if cell_a is not None else "—"
    return (
        td_ouvrant + f"<div>{val_a}</div>"
        '<div style="border-top:1px dotted #e0e0e0;'
        f'margin-top:1px;padding-top:1px;">{val_e}</div>'
        "</td>"
    )


def _label_cellule(libelle: str, sep: str, legende: str) -> str:
    """Cellule libellé de variable, avec rappel du modèle à la 1ʳᵉ variable.

    ``legende`` : ``"bi"`` rappelle ARPEGE/ECMWF (2 lignes, jours à deux
    modèles) ; ``"ecmwf"`` rappelle ECMWF seul (1 ligne, au passage à
    l'horizon ECMWF) ; ``""`` ne met rien.
    """
    contenu = libelle
    if legende:
        noms = "ARPEGE<br>ECMWF" if legende == "bi" else "ECMWF"
        contenu += (
            '<div style="font-weight:400;font-size:10px;color:#999;'
            f'line-height:1.5;margin-top:2px;">{noms}</div>'
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
    ecmwf_seul: bool,
    legende: str,
) -> str:
    """Table compacte d'un jour : Nuit / Jour, lignes variables.

    ``ecmwf_seul`` → cellules à une seule ligne (ECMWF), sinon ARPEGE+ECMWF
    empilés. ``legende`` (sur la 1ʳᵉ variable) rappelle le(s) modèle(s) au
    premier jour à deux modèles puis au premier jour ECMWF seul. Sur le
    **premier** jour, les en-têtes de fenêtre portent leur plage horaire (UTC).
    """
    nuit_lbl = "Nuit (18–6 h)" if premier else "Nuit"
    jour_lbl = "Jour (6–18 h)" if premier else "Jour"
    # En-tête de jour marqué (fond plus sombre + filet épais sombre dessous +
    # nom du jour en gras) pour séparer franchement les jours de la tendance.
    bord_jour = "border-bottom:2px solid #aeb6bd;"
    en_tete = (
        '<tr style="background:#e9edf0;">'
        '<th style="padding:6px 8px;text-align:left;color:#2c3e50;font-size:13px;'
        f'font-weight:700;{bord_jour}">{_date_fr_courte(jour)}</th>'
        '<th style="padding:6px 4px;text-align:center;font-size:11px;color:#888;'
        f'font-weight:400;{bord_jour}">{nuit_lbl}</th>'
        '<th style="padding:6px 4px;text-align:center;font-size:11px;color:#888;'
        f'font-weight:400;{bord_jour}">{jour_lbl}</th>'
        "</tr>"
    )
    lignes = [en_tete]
    for idx, (libelle_ligne, formatteur) in enumerate(_LIGNES_TENDANCE):
        # Séparateur de variable (bordure pleine) sur toutes sauf la première.
        sep = "" if idx == 0 else "border-top:1px solid #dcdcdc;"
        label = _label_cellule(libelle_ligne, sep, legende if idx == 0 else "")
        cellules = "".join(
            _cellule_modeles(
                agg_arpege.get((jour, fenetre)),
                agg_ecmwf.get((jour, fenetre)),
                fenetre,
                formatteur,
                sep,
                ecmwf_seul,
            )
            for fenetre in (FENETRE_NUIT, FENETRE_JOUR)
        )
        lignes.append("<tr>" + label + cellules + "</tr>")
    return (
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed;'
        'margin:14px 0;border:1px solid #d0d5da;border-radius:4px;">'
        + _GRILLE_COLGROUP
        + "".join(lignes)
        + "</table>"
    )


def _legende_tendance() -> str:
    """Légende de la tendance avec les **vrais pictos** (ciel, pluie, flèches ETP)."""

    def ic(code: int) -> str:
        return (
            f'<img src="{icone_base64(code)}" width="20" height="20" '
            'style="vertical-align:middle;">'
        )

    def fl(color: str, n: int) -> str:
        return f'<img src="{_fleche_etp_png(color, n)}" style="height:15px;vertical-align:middle;">'

    return (
        '<div style="margin:0 0 6px 0;font-size:11px;color:#888;line-height:1.9;">'
        "<strong>Picto ciel</strong> — ciel : "
        f"{ic(0)} clair · {ic(2)} nuageux · {ic(3)} couvert ; pluie : "
        f"{ic(61)} 1-5 · {ic(63)} 5-20 · {ic(65)} &gt; 20 mm/12 h.<br>"
        "À gauche du picto : <strong>proba</strong> pluie (%, MF officielle — "
        "indépendante des modèles ci-dessus, en tête de cellule). "
        "À droite, <strong>ETP</strong> : "
        '<span style="color:#bbb;">~</span> &lt; 1 mm · '
        f"{fl('#E6B800', 1)} 1-2 · {fl('#E67E00', 2)} 2-3 · {fl('#D11500', 3)} &gt; 3 mm.</div>"
    )


def bloc_tendance(
    agg_arpege: dict[tuple[pd.Timestamp, str], CelluleFenetre],
    agg_ecmwf: dict[tuple[pd.Timestamp, str], CelluleFenetre],
    horizon_jours: int,
    jour_min: pd.Timestamp | None = None,
) -> str:
    """Bloc tendance — une table empilée par jour.

    ARPEGE (haut) + ECMWF IFS (bas) tant qu'ARPEGE couvre le jour (≤ J+4) ;
    au-delà, une seule ligne ECMWF (jusqu'à J+10), sans ligne ARPEGE vide. La
    légende du modèle est rappelée au 1ᵉʳ jour à deux modèles puis au 1ᵉʳ jour
    ECMWF seul.

    ``jour_min`` (minuit UTC d'aujourd'hui) écarte le bout de passé que traîne le
    run ECMWF du créneau (12Z J-1) : la tendance démarre aujourd'hui.
    """
    jours = sorted({jour for (jour, _f) in {**agg_arpege, **agg_ecmwf}})
    if jour_min is not None:
        jours = [j for j in jours if j >= jour_min]
    jours = jours[:horizon_jours]
    if not jours:
        return ""
    tables: list[str] = []
    vu_ecmwf_seul = False
    for i, jour in enumerate(jours):
        a_arpege = any((jour, f) in agg_arpege for f in (FENETRE_NUIT, FENETRE_JOUR))
        ecmwf_seul = not a_arpege
        # Légende du modèle : une fois au 1ᵉʳ jour à deux modèles (ARPEGE/ECMWF),
        # puis une fois au 1ᵉʳ jour ECMWF seul (la ligne ARPEGE ayant disparu).
        if ecmwf_seul and not vu_ecmwf_seul:
            legende = "ecmwf"
            vu_ecmwf_seul = True
        elif not ecmwf_seul and i == 0:
            legende = "bi"
        else:
            legende = ""
        tables.append(
            _table_jour(
                jour,
                agg_arpege,
                agg_ecmwf,
                premier=(i == 0),
                ecmwf_seul=ecmwf_seul,
                legende=legende,
            )
        )
    legende = _legende_tendance()
    return (
        '<h3 style="margin:14px 0 4px 0;font-size:15px;color:#34495e;">'
        f"Tendance jusqu'à {horizon_jours} jours</h3>" + legende + "".join(tables)
    )


# --------------------------------------------------------------------------
# Guides de décision (rendu HTML statique, seuils config).
# --------------------------------------------------------------------------

_COULEUR_NIVEAU = {"critique": "#D55E00", "anticiper": "#E69F00", "info": "#7f8c8d"}

# Picto du guide « déficit hydrique » (regle_deficit_hydrique) — sous lui on
# place le lien vers l'atelier irrigation.
_PICTO_DEFICIT = "💧"

# Capture la proposition d'action en fin de titre (dernière parenthèse).
_ACTION_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")


def _rendre_guide(guide: GuideDecision) -> str:
    """Un guide : titre coloré + (si actif) l'action proposée sur une ligne « → »."""
    if guide.active:
        couleur = _COULEUR_NIVEAU.get(guide.niveau, "#7f8c8d")
        opacite = "1.0"
        poids = "700"
    else:
        couleur = "#9aa3a8"
        opacite = "0.7"
        poids = "400"
    # Pour un guide actif, la parenthèse finale est une proposition d'action →
    # on la sort sur une ligne « → … » dans le même bandeau (pour les inactifs,
    # la parenthèse est une note de seuil → on la laisse dans le titre).
    titre = guide.titre
    action = ""
    if guide.active:
        m = _ACTION_RE.match(titre)
        if m:
            titre, action = m.group(1), m.group(2)
    action_html = (
        f'<div style="font-size:13px;font-weight:600;color:{couleur};'
        f'margin:3px 0 0 24px;">→ {action}</div>'
        if action
        else ""
    )
    return (
        f'<div style="margin:6px 0;padding:8px 12px;border-left:4px solid {couleur};'
        f'background:#fbfbfb;border-radius:0 4px 4px 0;opacity:{opacite};">'
        f'<span style="font-size:18px;line-height:1;">{guide.picto}</span>'
        f'<span style="font-size:14px;font-weight:{poids};color:{couleur};margin-left:6px;">'
        f"{titre}</span>" + action_html + "</div>"
    )


def bloc_guides(guides: list[GuideDecision], atelier_url: str = "") -> str:
    """Guides groupés par thème ; lien atelier juste sous le guide déficit hydrique."""
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
    lien = _bloc_lien_atelier(atelier_url)
    sections: list[str] = []
    for theme, guides_theme in grouper_par_theme(guides):
        rendus: list[str] = []
        for g in guides_theme:
            rendus.append(_rendre_guide(g))
            if g.picto == _PICTO_DEFICIT:  # lien atelier juste sous le déficit hydrique
                rendus.append(lien)
        sections.append(
            '<h4 style="margin:12px 0 4px 0;font-size:13px;color:#34495e;'
            'border-bottom:1px solid #eee;padding-bottom:3px;">'
            f"{THEMES_LIBELLES[theme]}</h4>" + "".join(rendus)
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
        "<strong>Proba pluie</strong> : prévision officielle Météo-France calibrée "
        "(fenêtres 3 h/6 h), indépendante des deux modèles ci-dessus.",
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


def _bloc_lien_atelier(atelier_url: str) -> str:
    """Lien vers l'atelier irrigation (bilan hydrique interactif), si configuré.

    ``atelier_url`` vient de la config (``email.atelier_irrigation_url``) ; vide
    → pas de lien (dégradé gracieux, tant que l'app n'est pas déployée).
    """
    if not atelier_url:
        return ""
    return (
        '<div style="margin:14px 0 0 0;padding:10px 12px;background:#f0f6f4;'
        'border-radius:4px;font-size:12px;color:#34495e;">'
        f'💧 <a href="{atelier_url}" style="color:#009E73;font-weight:600;">'
        "Explorer le bilan hydrique</a>.</div>"
    )


def composer_guides_tendance(
    agg_arpege: dict[tuple[pd.Timestamp, str], CelluleFenetre],
    agg_ecmwf: dict[tuple[pd.Timestamp, str], CelluleFenetre],
    guides: list[GuideDecision],
    horizon_long: int,
    jour_min: pd.Timestamp | None = None,
    atelier_url: str = "",
    note_anomalie: str = "",
    rappel: bool = False,
) -> str:
    """Bloc « La semaine » : guides (avec lien atelier sous le déficit hydrique) +
    tendance. ``note_anomalie`` (HTML) est inséré après l'intro, avant les guides
    (ex. repli ARPEGE→ECMWF). ``rappel`` (mail d'après-midi) ajoute « pour rappel »
    à l'intro (semaine identique au matin). Les cartes sont regroupées avec le 48 h."""
    rappel_txt = (
        " <strong>Pour rappel</strong> : tendance du matin (mise à jour 1×/jour, run 00Z)."
        if rappel
        else ""
    )
    return (
        '<h2 style="margin:24px 0 8px 0;font-size:17px;color:#2c3e50;'
        'border-bottom:2px solid #2c3e50;padding-bottom:4px;">'
        "La semaine</h2>"
        '<p style="margin:0 0 8px 0;font-size:12px;color:#888;">'
        "Tendance et anticipation à moyen terme — horaires en <strong>UTC</strong> "
        "(la partie 48 h ci-dessus est en heure locale)."
        + rappel_txt
        + "</p>"
        + note_anomalie
        + bloc_guides(guides, atelier_url=atelier_url)
        + bloc_tendance(agg_arpege, agg_ecmwf, horizon_long, jour_min=jour_min)
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


def _bandeau_semaine_indisponible() -> str:
    """Section semaine réduite à un bandeau quand aucun modèle n'est disponible."""
    return (
        '<h2 style="margin:24px 0 8px 0;font-size:17px;color:#2c3e50;'
        'border-bottom:2px solid #2c3e50;padding-bottom:4px;">La semaine</h2>'
        '<div style="margin:6px 0;padding:10px 12px;background:#fff8e1;'
        "border-left:3px solid #E69F00;border-radius:0 3px 3px 0;font-size:13px;"
        "color:#8a6d3b;\">Section semaine indisponible aujourd'hui : les runs modèles "
        "(ARPEGE et ECMWF) ne sont pas publiés. Voir le rapport de bug en fin de mail.</div>"
    )


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
    atelier_url: str = "",
    rappel: bool = False,
    source_arpege_mf: Any = None,
    proba_mf: pd.Series | None = None,
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
    rappel :
        ``True`` pour le mail d'après-midi : la semaine est identique à celle du
        matin (même run 00Z) → on l'étiquette « pour rappel » (pas une nouvelle
        actualisation ; la tendance est mise à jour une fois par jour).
    proba_mf :
        Proba pluie (%) **officielle MF calibrée** par bin (début UTC → %),
        ``PrevisionMF.proba_bins`` récupérée par App 1. Signal autonome (ni
        ARPEGE ni ECMWF), agrégé par fenêtre 12 h et affiché en tête de cellule.
        ``None`` (ou vide, ex. repli ARPEGE) → pas de proba (dégradation gracieuse).
    """
    anomalies: list[Anomalie] = []
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

        # La tendance longue est un produit **une fois par jour** (run 00Z J) :
        # on force le créneau "matin" dans les deux envois. L'après-midi rappelle
        # ainsi la tendance du matin à l'identique (run déterministe → mêmes
        # données), et reste alignée sur l'atelier irrigation (00Z, une maj/jour).
        jour = now_utc.normalize()
        runs = runs_du_creneau("matin", jour)
        run_arpege = runs[ARPEGE]
        run_ecmwf = runs[ECMWF_HRES]

        # ARPEGE : Open-Meteo (défaut) ou MF Données Publiques en direct (flag).
        # En MF direct, l'indisponibilité retombe sur la cascade (df_arpege=None →
        # repli ECMWF), comme un run muet. ECMWF reste sur Open-Meteo.
        if sm.get("arpege_mf_direct", False):
            from meteo_socle.sources.meteofrance_arpege import (
                ArpegeIndisponibleError,
                MeteoFranceArpege,
            )

            src_mf = source_arpege_mf or MeteoFranceArpege()
            try:
                df_arpege = src_mf.obtenir_run(
                    run_arpege, lat, lon, horizon_court, cache_dir=sm.get("arpege_cache_dir")
                )
            except ArpegeIndisponibleError as e:
                logger.warning("Semaine : ARPEGE direct MF indisponible (%s) → cascade.", e)
                df_arpege = None
        else:
            df_arpege = source.obtenir_run(
                ARPEGE, run_arpege, lat, lon, horizon_court, VARS_MONO_MODELE
            )
        df_ecmwf = source.obtenir_run(ECMWF, run_ecmwf, lat, lon, horizon_long, VARS_MONO_MODELE)
        arpege_ok = df_arpege is not None and not df_arpege.empty
        ecmwf_ok = df_ecmwf is not None and not df_ecmwf.empty

        if not arpege_ok:
            logger.warning("Semaine : run ARPEGE %s muet.", run_arpege)
            anomalies.append(
                Anomalie(
                    "La semaine",
                    "ARPEGE indisponible, repli sur ECMWF" if ecmwf_ok else "ARPEGE indisponible",
                    f"Run ARPEGE {run_arpege:%Y-%m-%dT%H:%M}Z muet/indisponible sur "
                    "Open-Meteo single-runs (meteofrance_arpege_europe, non publié au "
                    "moment du fetch).",
                )
            )
        if not ecmwf_ok:
            logger.warning("Semaine : run ECMWF %s muet.", run_ecmwf)
            anomalies.append(
                Anomalie(
                    "La semaine",
                    "ECMWF indisponible, tendance limitée à ARPEGE"
                    if arpege_ok
                    else "ECMWF indisponible",
                    f"Run ECMWF {run_ecmwf:%Y-%m-%dT%H:%M}Z muet/indisponible sur Open-Meteo "
                    "single-runs (modèle ecmwf_ifs025, non publié au moment du fetch).",
                )
            )

        # Couverture PARTIELLE (run publié partiellement / trou d'ingestion) : la
        # donnée existe mais s'arrête avant l'horizon attendu. Le garde-fou de
        # `agreger_par_fenetre` écarte alors les fenêtres tronquées (jamais de
        # faux extrême) — mais cette absence serait MUETTE (le jour basculerait en
        # « autre modèle seul », indistinct). Anormal ≠ 1re nuit incomplète : on
        # le rend VISIBLE (anomalie → rapport de bug + note inline).
        for nom, df_m, run_m, horizon_m in (
            ("ARPEGE", df_arpege if arpege_ok else None, run_arpege, horizon_court),
            ("ECMWF", df_ecmwf if ecmwf_ok else None, run_ecmwf, horizon_long),
        ):
            if df_m is None:
                continue
            attendu = run_m + pd.Timedelta(days=horizon_m)
            fin = df_m.index.max()
            if fin < attendu - pd.Timedelta(hours=12):
                manque_j = (attendu - fin).total_seconds() / 86400
                logger.warning(
                    "Semaine : %s écourté (jusqu'à %s, attendu ~%d j).", nom, fin, horizon_m
                )
                anomalies.append(
                    Anomalie(
                        "La semaine",
                        f"{nom} publié partiellement — tendance écourtée",
                        f"Run {nom} {run_m:%Y-%m-%dT%H:%M}Z : données jusqu'à "
                        f"{fin:%Y-%m-%dT%H:%M}Z seulement (attendu ~{horizon_m} j, "
                        f"manque ~{manque_j:.1f} j). Les jours non couverts n'affichent "
                        f"pas les valeurs {nom} (écartées : jamais de valeur extrapolée).",
                    )
                )

        # Les deux modèles muets → bandeau d'indisponibilité (le détail va au
        # rapport de bug). Le mail 48 h part quand même.
        if not arpege_ok and not ecmwf_ok:
            return {
                "guides_tendance_html": _bandeau_semaine_indisponible(),
                "cartes_geo": None,
                "sources_html": "",
                "texte": "GUIDES DE DÉCISION : section indisponible (runs modèles non publiés).",
                "anomalies": anomalies,
            }

        # Proba pluie : **proba officielle MF calibrée** (signal autonome, ni
        # ARPEGE ni ECMWF — cf. probability_forecast, ~J+10), déjà récupérée par
        # App 1 et passée via ``proba_mf`` (bins UTC → %). Agrégée par fenêtre
        # 12 h (max), puis injectée sur la **ligne du haut** de chaque cellule :
        # ARPEGE quand il couvre le jour (J0-J4), sinon ECMWF (J5-J10). Ainsi la
        # proba s'affiche une seule fois par cellule et se lit comme la proba de
        # la période, pas celle d'un modèle. Absente (repli) → pas de proba.
        proba_fenetre = proba_max_par_fenetre(proba_mf, "UTC", horizon_long)

        # Agrégations tendance — dict vide pour un modèle absent (bloc_tendance
        # gère nativement un modèle manquant : cellules de l'autre modèle seul).
        agg_arpege: dict[tuple[pd.Timestamp, str], CelluleFenetre] = {}
        agg_ecmwf: dict[tuple[pd.Timestamp, str], CelluleFenetre] = {}
        if arpege_ok:
            agg_arpege = agreger_par_fenetre(
                df_arpege, "UTC", horizon_long, etp_horaire_socle(df_arpege, site), proba_fenetre
            )
        if ecmwf_ok:
            # ECMWF ne porte la proba que sur les fenêtres non couvertes par
            # ARPEGE (au-delà de J+4) → une seule proba par cellule, en tête.
            proba_ecmwf = {k: v for k, v in proba_fenetre.items() if k not in agg_arpege}
            agg_ecmwf = agreger_par_fenetre(
                df_ecmwf, "UTC", horizon_long, etp_horaire_socle(df_ecmwf, site), proba_ecmwf
            )

        # Guides : indicateurs quotidiens depuis J+0 00Z, sur horizon_court jours
        # (cohérent atelier streamlit). ARPEGE par défaut ; repli ECMWF si ARPEGE
        # muet — mêmes variables (T, pluie, rayonnement) → mêmes indicateurs.
        df_guides = df_arpege if arpege_ok else df_ecmwf
        quotidien = calculer_indicateurs_quotidiens(
            df_guides, config_op, now_utc=now_utc.normalize()
        )
        quotidien = jours_complets_seulement(quotidien, df_guides).head(horizon_court)
        tz_site = site.get("tz", "Europe/Paris")
        today_local = now_utc.tz_convert(tz_site).normalize().tz_localize(None)
        guides = evaluer_decisions(quotidien, exploitation, today_local)

        # Cartes ARPEGE-Europe : seulement si ARPEGE dispo (sinon hors sujet).
        if cartes_geo is None and fetch_cartes and arpege_ok:
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

        note = note_inline(" ; ".join(a.resume for a in anomalies)) if anomalies else ""
        return {
            "guides_tendance_html": composer_guides_tendance(
                agg_arpege,
                agg_ecmwf,
                guides,
                horizon_long,
                jour_min=now_utc.normalize(),
                atelier_url=atelier_url,
                note_anomalie=note,
                rappel=rappel,
            ),
            "cartes_geo": cartes_geo,
            "sources_html": bloc_sources_semaine(
                horizon_court, horizon_long, run_arpege, run_ecmwf
            ),
            "texte": composer_section_semaine_texte(guides),
            "anomalies": anomalies,
        }
    except Exception as e:  # noqa: BLE001 — la semaine ne doit jamais casser la 48 h
        logger.error("Semaine : composition échouée : %s", e)
        return {
            "guides_tendance_html": _bandeau_semaine_indisponible(),
            "cartes_geo": None,
            "sources_html": "",
            "texte": "GUIDES DE DÉCISION : section indisponible (erreur de composition).",
            "anomalies": [
                Anomalie(
                    "La semaine",
                    "Section semaine indisponible (erreur interne)",
                    f"{type(e).__name__}: {e}",
                )
            ],
        }
