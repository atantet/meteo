"""Composition de l'email matinal Veille (texte + HTML mobile-first).

Génère sujet, corps texte (fallback) et corps HTML responsive à partir
des indicateurs et alertes calculés.

Le ton reste informationnel (cf. principe n°1). L'utilisateur garde
son jugement empirique pour décider.

Chaque indicateur est annoté de sa **fenêtre temporelle** (entre
crochets, gris discret) et le footer du mail rappelle la **source des
données** + la **méthode de calcul ETP** + la programmation du cron
(principe n°5 transparence).

**Palette de couleurs** : Bang Wong 2011 (Nature Methods), choisie pour
être distinguable par les daltoniens (deutéranopie + protanopie,
~8 % des hommes) :

- ``#0072B2`` bleu profond — T° min (froid)
- ``#D55E00`` vermillon — T° max, alertes critiques, déficit hydrique
- ``#56B4E9`` bleu ciel — pluie
- ``#009E73`` vert bleuté — vent moyen, bilan hydrique positif, OK
- ``#E69F00`` orange — rafales, warnings

Les valeurs numériques sont rendues en ``font-weight:700`` pour
hiérarchie visuelle ; les labels gauches restent en gris discret.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

# Helpers FR partagés avec App 2 Opérationnelle, cf. apps/shared/dates_fr.py.
from apps.shared.dates_fr import (
    JOURS_FR,
    MOIS_FR,
    format_date_fr,
    format_horodatage_fr,
    format_t0_court,
)
from meteo_socle.sources.meteofrance_vigilance import (
    NIVEAU_NOMS as VIGILANCE_NIVEAU_NOMS,
)
from meteo_socle.sources.meteofrance_vigilance import (
    VigilanceDepartement,
)

from .alertes import Alerte, resume_alertes
from .cartes_synoptiques import (
    METEOCIEL_PAGE_AFFICHEE,
    METOFFICE_PAGE_AFFICHEE,
    CartesGrille,
)
from .indicateurs import (
    IndicateursVeille,
    degrees_to_cardinal,
    direction_dominante_vecteur,
    moment_envoi,
    periodes_pleines,
    portion_horaire,
)

__all__ = [
    # Re-exports pour rétro-compat (les tests historiques importaient
    # depuis apps.veille.email).
    "JOURS_FR",
    "MOIS_FR",
    "format_date_fr",
    "format_horodatage_fr",
    "format_t0_court",
    "EmailComposed",
    "composer_sujet",
    "composer_texte",
    "composer_html",
    "composer_email",
]


@dataclass
class EmailComposed:
    """Triplet sujet / texte / HTML prêt à envoyer."""

    sujet: str
    texte: str
    html: str


# Source = prévision officielle Météo-France (ADR-0014). Plus de modèles bruts
# ni de runs : un produit fusionné/expertisé, étiqueté par sa fraîcheur (updated_on).
SOURCE_MF = "Prévision officielle Météo-France (webservice.meteofrance.com)"
CRON_EXPLAIN = "6 h 30 et 18 h 30 (heure locale)"
SITE_EXPLAIN = "8 La Petite Claye, 35610 Pleine-Fougères (48.5420 N, 1.6155 W, alt 30 m)"


def label_source_mf(updated_on: pd.Timestamp | None, tz_locale: str = "Europe/Paris") -> str:
    """Libellé « Source » = prévision officielle MF + sa fraîcheur (ADR-0014 D1/D9).

    ``updated_on`` (tz-aware UTC) est l'heure d'émission officielle de la prévi
    (champ ``updated_on`` du webservice). Affichée en heure locale.
    """
    if updated_on is None:
        return SOURCE_MF
    loc = updated_on.tz_convert(tz_locale)
    return f"{SOURCE_MF} · mise à jour {loc.strftime('%d/%m %Hh%M %Z')}"


# Repli si ``updated_on`` non fourni (appel legacy / test).
SOURCE_DEFAUT = SOURCE_MF


def _bloc_chart(chart_base64: str) -> str:
    """Bloc HTML pour le graphique 48 h embarqué (vide si non fourni)."""
    if not chart_base64:
        return ""
    return (
        '<div style="margin:12px 0;text-align:center;">'
        f'<img src="{chart_base64}" alt="Prévision 48 h" '
        'style="max-width:100%;height:auto;border-radius:4px;">'
        "</div>"
    )


def _libelle_decalage_utc(
    prevision_horaire: pd.DataFrame | None,
    tz_locale: str = "Europe/Paris",
) -> str:
    """Texte discret du décalage UTC↔local sur la fenêtre (ex. « CEST = UTC+2 »).

    La série temporelle est en **UTC** (axe fixe, ADR-0014) ; ce libellé aide à
    convertir mentalement vers l'heure locale. Renvoie les **deux** décalages
    (« CET = UTC+1 / CEST = UTC+2 ») si la fenêtre chevauche un changement
    d'heure, ou « » si la prévision est absente.
    """
    if prevision_horaire is None or prevision_horaire.empty:
        return ""
    idx = pd.DatetimeIndex(prevision_horaire.index).tz_convert(tz_locale)
    paires: dict[str, int] = {}
    for ts in idx:
        offset = ts.utcoffset()
        nom = ts.tzname()
        if offset is None or nom is None:
            continue
        paires[nom] = int(offset.total_seconds() // 3600)
    parts = [f"{nom} = UTC{h:+d}" for nom, h in sorted(paires.items(), key=lambda p: p[1])]
    return " / ".join(parts)


DWD_URL_AFFICHEE = (
    "https://www.dwd.de/DWD/wetter/wv_spez/hobbymet/wetterkarten/bwk_bodendruck_na_ana.png"
)


def _bloc_carte_synoptique(
    carte_base64: str,
    last_modified: datetime | None = None,
    source_url: str = DWD_URL_AFFICHEE,
    tz_locale: str = "Europe/Paris",
) -> str:
    """Bloc HTML pour la carte synoptique DWD (vide si non fournie).

    ``last_modified`` (datetime UTC) — heure de production de l'analyse
    côté DWD lue dans le header HTTP. Affichée localisée + lien vers
    l'URL source pour traçabilité (principe #5).
    """
    if not carte_base64:
        return ""
    legende = (
        'Analyse de surface — <a href="' + source_url + '" '
        'style="color:#888;text-decoration:underline;">Deutscher Wetterdienst</a>'
    )
    if last_modified is not None:
        lm_loc = last_modified.astimezone(ZoneInfo(tz_locale))
        legende += f" · mise à jour {lm_loc.strftime('%d/%m %Hh%M %Z')}"
    else:
        legende += " · mise à jour 4×/jour"
    return (
        '<div style="margin:18px 0 6px 0;">'
        '<h3 style="margin:0 0 6px 0;font-size:15px;color:#34495e;">'
        "Situation synoptique</h3>"
        '<div style="text-align:center;">'
        f'<img src="{carte_base64}" alt="Analyse de surface DWD" '
        'style="max-width:100%;height:auto;border-radius:4px;border:1px solid #eee;">'
        "</div>"
        '<p style="margin:4px 0 0 0;font-size:11px;color:#888;text-align:center;">'
        f"{legende}"
        "</p>"
        "</div>"
    )


# Palette pour les niveaux Vigilance MF (texte foncé sur fond clair pour
# le tableau ; cellules colorées pour les non-verts → lisible mobile).
_VIGILANCE_COULEURS = {
    1: {"bg": "#f4f4f4", "fg": "#7f8c8d"},  # Vert (rendu neutre, pas vert criard)
    2: {"bg": "#fff4d1", "fg": "#9a7000"},  # Jaune
    3: {"bg": "#ffd9b3", "fg": "#a04000"},  # Orange
    4: {"bg": "#ffcccc", "fg": "#a00000"},  # Rouge
}

VIGILANCE_URL_AFFICHEE = "https://vigilance.meteofrance.fr/fr"


#: Au-delà de cet âge, la carte Vigilance est considérée non rafraîchie pour le
#: cycle courant (publication ≥ 2×/jour à 6 h/16 h locales — ADR-0014 D10). Le
#: critère porte sur l'ÂGE (deux instants absolus) → insensible au fuseau.
VIGILANCE_AGE_MAX = pd.Timedelta(hours=12)


def _bloc_vigilance_mf(
    vigilance: VigilanceDepartement | None,
    tz_locale: str = "Europe/Paris",
    now: pd.Timestamp | None = None,
) -> str:
    """Bloc HTML Vigilance Météo-France pour le département configuré.

    - ``None`` (clé API non configurée, ou fetch échoué) → bloc vide.
    - Tout vert → ligne compacte "tout vert".
    - ≥ 1 phénomène ≥ jaune → mini-tableau filtrant les phénomènes
      non-verts, avec niveaux J et J+1 colorés.

    Source officielle d'État. Référence légale pour les phénomènes
    dangereux (cf. méthodo "une seule méthode par phénomène").
    """
    if vigilance is None:
        return ""

    update_loc = vigilance.update_time.tz_convert(tz_locale)
    legende = (
        f'<a href="{VIGILANCE_URL_AFFICHEE}" '
        'style="color:#888;text-decoration:underline;">Vigilance Météo-France</a> · '
        f"département {vigilance.departement} · "
        f"mise à jour {update_loc.strftime('%d/%m %Hh%M %Z')}"
    )
    # Fraîcheur (ADR-0014 D10) : carte plus vieille que ~12 h → l'actualisation du
    # cycle courant (6 h/16 h locales) n'est pas encore publiée. On le signale,
    # sans retry (si systématique, retarder le cron).
    if now is not None and (now - vigilance.update_time) > VIGILANCE_AGE_MAX:
        legende += (
            ' · <span style="color:#a04000;">⚠ actualisation du cycle non encore publiée</span>'
        )

    # Tous verts : on garde le titre de section (cohérence avec le cas
    # "alerte présente") puis une ligne "rien à signaler" sur 48 h.
    if vigilance.niveau_max_global <= 1:
        return (
            '<div style="margin:12px 0 6px 0;">'
            '<h3 style="margin:0 0 6px 0;font-size:15px;color:#34495e;">'
            "Vigilance Météo-France</h3>"
            '<div style="padding:8px 12px;background:#f4f4f4;border-radius:4px;'
            'font-size:12px;color:#555;">'
            f"Aucune alerte sur les 48 h (département {vigilance.departement})."
            '<div style="font-size:11px;color:#888;margin-top:4px;">'
            f"{legende}</div>"
            "</div>"
            "</div>"
        )

    # Filtre phénomènes non-verts pour réduire le bruit.
    actifs = [p for p in vigilance.phenomenes if p.niveau_max > 1]

    def cellule_niveau(niveau: int) -> str:
        c = _VIGILANCE_COULEURS.get(niveau, _VIGILANCE_COULEURS[1])
        return (
            f'<td style="padding:4px 8px;text-align:center;'
            f"background:{c['bg']};color:{c['fg']};font-weight:600;"
            'font-size:12px;border:1px solid #fff;">'
            f"{VIGILANCE_NIVEAU_NOMS[niveau]}"
            "</td>"
        )

    lignes_html: list[str] = []
    for p in actifs:
        lignes_html.append(
            "<tr>"
            '<td style="padding:4px 8px;color:#555;font-size:12px;">'
            f"{p.nom}</td>" + cellule_niveau(p.niveau_j) + cellule_niveau(p.niveau_j1) + "</tr>"
        )

    return (
        '<div style="margin:12px 0 6px 0;">'
        '<h3 style="margin:0 0 6px 0;font-size:15px;color:#34495e;">'
        "Vigilance Météo-France</h3>"
        '<table cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;border-collapse:collapse;'
        'border:1px solid #eee;border-radius:4px;overflow:hidden;">'
        '<tr style="background:#fafafa;">'
        '<th style="padding:6px 8px;text-align:left;font-size:11px;color:#888;'
        'font-weight:600;">Phénomène</th>'
        '<th style="padding:6px 8px;text-align:center;font-size:11px;color:#888;'
        "font-weight:600;\">Aujourd'hui</th>"
        '<th style="padding:6px 8px;text-align:center;font-size:11px;color:#888;'
        'font-weight:600;">Demain</th>'
        "</tr>" + "".join(lignes_html) + "</table>"
        '<p style="margin:4px 0 0 0;font-size:11px;color:#888;">'
        f"{legende}"
        "</p>"
        "</div>"
    )


def _bloc_vigilance_exploitation(alertes: list[Alerte]) -> str:
    """Bloc HTML Vigilance exploitation — seuils agronomiques configurés.

    Pendant local de la Vigilance Météo-France : seuils propres à
    l'exploitation (gel, risque maladies…).
    Affiché juste après la Vigilance MF pour que les deux "rien à
    signaler" soient explicitement séparés — pas de bandeau vert global
    qui laisserait croire à un « tout va bien » alors que MF peut être
    en vigilance orages (incohérence constatée 2026-06-01).

    - Aucune alerte → on garde le titre de section + ligne grise
      "Aucune alerte sur les 48 h" (même style que le cas MF vide).
    - ≥ 1 alerte → items colorés par niveau (warning / critique).
    """
    if not alertes:
        return (
            '<div style="margin:12px 0 6px 0;">'
            '<h3 style="margin:0 0 6px 0;font-size:15px;color:#34495e;">'
            "Vigilance exploitation</h3>"
            '<div style="padding:8px 12px;background:#f4f4f4;border-radius:4px;'
            'font-size:12px;color:#555;">Aucune alerte sur les 48 h.</div>'
            "</div>"
        )

    couleur_niveau = {"critique": "#D55E00", "warning": "#E69F00"}
    items: list[str] = []
    for a in alertes:
        c = couleur_niveau.get(a.niveau, "#7f8c8d")
        items.append(
            f'<div style="margin:6px 0;padding:8px 12px;background:{c};'
            f'color:white;border-radius:4px;">'
            f"<strong>{a.titre}</strong>"
            f'<div style="font-size:0.85em;opacity:0.9;">'
            f"seuil configuré : {a.seuil} {a.unite}</div>"
            f"</div>"
        )
    return (
        '<div style="margin:12px 0 6px 0;">'
        '<h3 style="margin:0 0 6px 0;font-size:15px;color:#34495e;">'
        "Vigilance exploitation</h3>" + "".join(items) + "</div>"
    )


def _bloc_definitions(seuils: dict[str, Any] | None) -> str:
    """Seuils de Vigilance exploitation en pied de mail (11 px gris, comme les sources).

    Transparence (principe #5) : les seuils EXACTS qui déclenchent la
    Vigilance exploitation, lus dans la config (pas en dur). Les
    phénomènes dangereux (canicule, pluie, vent, orages) sont délégués à
    la Vigilance d'État (une seule méthode par phénomène).
    """
    seuils = seuils or {}

    def _def(terme: str, texte: str) -> str:
        return (
            f'<div style="margin:2px 0;">'
            f'<strong style="color:#555;">{terme}</strong> : {texte}</div>'
        )

    seuils_lignes: list[str] = []
    g = seuils.get("gel", {})
    if g.get("actif"):
        seuils_lignes.append(
            _def(
                "Gel",
                f"T° min ≤ {g['seuil_celsius']:.0f} °C sur une plage de 6 h "
                "(nuit/matin/midi/soir) — purge eau & voilage.",
            )
        )
    rm = seuils.get("risque_maladies", {})
    if rm.get("actif"):
        seuils_lignes.append(
            _def(
                "Risque maladies",
                f"T° min nuit prochaine ≥ {rm['t_min_nuit_celsius']:.0f} °C.",
            )
        )
    seuils_lignes.append(
        _def(
            "Canicule, pluie, vent, orages",
            "relèvent de la Vigilance d'État (Météo-France) affichée plus haut.",
        )
    )

    return (
        '<div style="margin-top:12px;padding-top:12px;border-top:1px solid #eee;'
        'font-size:11px;color:#888;line-height:1.5;">'
        '<div style="font-weight:600;color:#555;margin-bottom:4px;">'
        "Seuils de Vigilance exploitation</div>" + "".join(seuils_lignes) + "</div>"
    )


def _format_dt_court_fr(dt: pd.Timestamp) -> str:
    """Formate un instant en français court : ``lun. 01/06 08 h``."""
    jour_court = JOURS_FR[dt.weekday()][:3] + "."
    return f"{jour_court} {dt.day:02d}/{dt.month:02d} {dt.hour:02d} h"


def _bloc_cartes_synoptiques(
    grille: CartesGrille | None,
    tz_locale: str = "Europe/Paris",
) -> str:
    """Bloc HTML 2 sections empilées — Met Office puis AROME, 1 colonne.

    Chaque section indique le **run** dont les cartes sont issues ;
    chaque image porte sa **cible** (heure de validité) en heure locale.
    L'utilisateur sait donc toujours de quand date la prévi et pour
    quelle heure elle vaut.

    Vide si ``grille`` est ``None`` ou si aucune carte n'a été
    récupérée avec succès. Les cartes individuelles manquantes sont
    silencieusement sautées.

    Layout :

    +---------------- Situation synoptique --------------------+
    | Met Office UK — surface (Atlantique nord / Europe)        |
    | Run lun. 01/06 02 h                                       |
    |   Cible : lun. 01/06 02 h                                 |
    |   [carte 1]                                               |
    |   Cible : mar. 02/06 02 h                                 |
    |   [carte 2]                                               |
    |   Cible : mer. 03/06 02 h                                 |
    |   [carte 3]                                               |
    +-----------------------------------------------------------+
    | Météociel AROME 1.3 km — France (précip + iso + nébu)     |
    | Run dim. 31/05 20 h (veille)                              |
    |   Cible : lun. 01/06 08 h                                 |
    |   [carte 4]                                               |
    |   Cible : mar. 02/06 02 h                                 |
    |   [carte 5]                                               |
    |   Cible : mar. 02/06 20 h                                 |
    |   [carte 6]                                               |
    +-----------------------------------------------------------+
    """
    if grille is None or grille.nb_disponibles == 0:
        return ""

    def cartes_section(
        cartes,
        titre: str,
        source_url: str,
        alt_prefix: str,
        run_suffixe: str = "",
    ) -> str:
        if not cartes:
            return ""
        run_loc = cartes[0].run_utc.tz_convert(tz_locale)
        sous_titre = f"Run {_format_dt_court_fr(run_loc)}{run_suffixe} (heure locale)"
        lignes: list[str] = [
            '<div style="margin:10px 0 6px 0;">'
            '<h4 style="margin:0 0 2px 0;font-size:13px;color:#34495e;'
            'font-weight:600;">'
            f'<a href="{source_url}" style="color:#34495e;text-decoration:none;">'
            f"{titre}</a></h4>"
            f'<div style="font-size:11px;color:#888;margin-bottom:4px;">{sous_titre}</div>'
            "</div>"
        ]
        for c in cartes:
            cible_loc = c.cible_utc.tz_convert(tz_locale)
            cible_label = f"Cible : {_format_dt_court_fr(cible_loc)}"
            if not c.data_uri:
                lignes.append(
                    '<p style="text-align:center;color:#bbb;font-size:11px;'
                    f'margin:6px 0;">{cible_label} — carte indisponible</p>'
                )
                continue
            lignes.append(
                '<div style="text-align:center;margin:6px 0 10px 0;">'
                '<div style="font-size:11px;color:#888;margin-bottom:2px;">'
                f"{cible_label}"
                "</div>"
                f'<img src="{c.data_uri}" alt="{alt_prefix} — {cible_label}" '
                'style="max-width:100%;height:auto;border-radius:4px;'
                'border:1px solid #eee;">'
                "</div>"
            )
        return "".join(lignes)

    section_metoffice = cartes_section(
        grille.metoffice,
        titre="Met Office UK — surface (Atlantique nord / Europe, fronts)",
        source_url=METOFFICE_PAGE_AFFICHEE,
        alt_prefix="Met Office surface",
    )
    section_arome = cartes_section(
        grille.arome,
        titre="Météociel AROME 1.3 km — France (précip + pression + nébulosité)",
        source_url=METEOCIEL_PAGE_AFFICHEE,
        alt_prefix="AROME résumé France",
        run_suffixe=" (veille)",
    )

    return (
        '<div style="margin:18px 0 6px 0;">'
        '<h3 style="margin:0 0 6px 0;font-size:15px;color:#34495e;">'
        "Situation synoptique</h3>"
        f"{section_metoffice}"
        f"{section_arome}"
        "</div>"
    )


def _tendance_texte_48h(
    prevision_horaire: pd.DataFrame | None,
    tz_locale: str = "Europe/Paris",
) -> list[str]:
    """Tendance texte 48 h équivalente à la bande pictos HTML.

    Renvoie une liste de lignes (1 par jour) du style :
    "  Sam 30/05 : matin Clair → midi Pluie modérée → soir Couvert"
    """
    if prevision_horaire is None or "weather_code" not in prevision_horaire.columns:
        return []

    from apps.shared.pictograms import code_dominant_fenetre, libelle

    horaire_loc = prevision_horaire.copy()
    horaire_loc.index = pd.DatetimeIndex(horaire_loc.index).tz_convert(tz_locale)
    horaire_48h = horaire_loc.head(48)
    if horaire_48h.empty:
        return []

    jours_uniques = pd.DatetimeIndex(horaire_48h.index).normalize().unique()[:2]
    fenetres = (("matin", 6, 12), ("midi", 12, 16), ("soir", 16, 21))
    lignes: list[str] = []
    for jour in jours_uniques:
        jour_label = JOURS_FR[jour.weekday()][:3] + f" {jour.day:02d}/{jour.month:02d}"
        parts = []
        for nom_fenetre, h_debut, h_fin in fenetres:
            masque = (horaire_48h.index.normalize() == jour) & (
                (horaire_48h.index.hour >= h_debut) & (horaire_48h.index.hour < h_fin)
            )
            code = code_dominant_fenetre(horaire_48h.loc[masque, "weather_code"])
            # Fenêtre non couverte (bord de fenêtre : l'après-midi, la prévision
            # démarre à 12Z → la « matin » du 1er jour est vide) → on la saute.
            if code is None:
                continue
            parts.append(f"{nom_fenetre} {libelle(code)}")
        if parts:
            lignes.append(f"  {jour_label} : " + " → ".join(parts))
    return lignes


MS_TO_KMH_VEILLE = 3.6
# 4 quartiers de 6 h égaux, en heure locale, intervalles fermés à gauche
# et ouverts à droite : [h_debut, h_fin). Couvrent les 24 h du jour
# affiché. Aucun rollover ; la nuit affichée est la nuit DU jour J
# (donc déjà passée pour J0 si T+0 > 06 h locale, c'est attendu).
FENETRES_VEILLE = (
    ("Nuit", 0, 6),
    ("Matin", 6, 12),
    ("Après-midi", 12, 18),
    ("Soir", 18, 24),
)

# Choix du picto : la nuit (lune au lieu du soleil) est définie par la
# période locale [0, 6) pour l'App 1 — c.-à-d. la seule fenêtre "Nuit".
# (L'App 2 utilise sa propre convention [0, 7) ∪ [19, 24) ; les deux
# apps gardent volontairement leur découpage.) Un créneau est "nuit"
# si toutes ses heures tombent dans [0, FENETRE_NUIT_PICTO_FIN).
FENETRE_NUIT_PICTO_FIN = 6

# Largeurs de colonnes FIXES pour la grille Tendance. Chaque jour est une
# ``<table>`` distincte ; sans largeurs imposées, chacune cale ses colonnes
# sur son propre contenu et les jours se désalignent — surtout l'après-midi
# où le 1er jour a des fenêtres vides (« — »). Avec ``table-layout:fixed``
# + ce ``colgroup`` identique partout (1 colonne libellé + 4 fenêtres), les
# tableaux jour à jour sont parfaitement alignés.
_GRILLE_COLGROUP = (
    '<colgroup><col style="width:32%">' + '<col style="width:17%">' * 4 + "</colgroup>"
)


def _unite(texte: str) -> str:
    """Span unité discret (gris clair, plus petit) à coller après une valeur."""
    return f'<span style="color:#aaa;font-weight:400;font-size:11px;">&nbsp;{texte}</span>'


# Flèche pointant dans la direction où va le vent (convention scientifique,
# wind barbs). N (vent venant du nord) => air se déplace vers le sud =>
# flèche pointe ↓. Le cardinal d'origine est rappelé en petit à côté.
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


def _masque_fenetre(horaire_loc: pd.DataFrame, jour: pd.Timestamp, h_debut: int, h_fin: int):
    """Masque booléen pour une fenêtre intra-jour ``[h_debut, h_fin)`` en heure locale.

    ``horaire_loc`` doit être indexé tz-aware sur la zone locale (déjà
    converti par l'appelant) — l'attribut ``.hour`` est lu directement.
    """
    return (horaire_loc.index.normalize() == jour) & (
        (horaire_loc.index.hour >= h_debut) & (horaire_loc.index.hour < h_fin)
    )


def _serie_fenetre(
    horaire_loc: pd.DataFrame,
    jour: pd.Timestamp,
    colonne: str,
    h_debut: int,
    h_fin: int,
) -> pd.Series:
    """Sous-série d'une colonne sur la fenêtre ``[h_debut, h_fin)`` du jour local."""
    if colonne not in horaire_loc.columns:
        return pd.Series([], dtype=float)
    return horaire_loc.loc[_masque_fenetre(horaire_loc, jour, h_debut, h_fin), colonne].dropna()


def _bloc_grille_indicateurs_48h(
    prevision_horaire: pd.DataFrame | None,
    now_utc: pd.Timestamp | None = None,
    tz_locale: str = "Europe/Paris",
) -> str:
    """Grille par période de 6 h locale — pictos + T° + Pluie + Vent + HR (ADR-0014).

    Découpage sur les **périodes de 6 h pleines** de la prévi officielle MF
    (``periodes_pleines`` sur la portion horaire) : 1ʳᵉ période courante (non
    encore écoulée à l'heure d'envoi ``now_utc``) → dernière pleine. Le picto
    vient du ``weather_code`` MF (cohérent avec le cumul MF, ADR-0014).
    """
    if prevision_horaire is None:
        return ""

    from apps.shared.pictograms import code_dominant_fenetre, icone_base64, libelle

    horaire = prevision_horaire.copy()
    horaire.index = pd.DatetimeIndex(horaire.index).tz_convert(tz_locale)
    horaire = portion_horaire(horaire)
    apres = now_utc.tz_convert(tz_locale) if now_utc is not None else None
    periodes = periodes_pleines(horaire, apres=apres)
    if not periodes:
        return ""

    # Périodes pleines à afficher : clé (jour local normalisé, heure de début).
    pleins = {(debut.normalize(), debut.hour) for _, debut, _ in periodes}
    jours_uniques = sorted({debut.normalize() for _, debut, _ in periodes})
    tableaux: list[str] = []

    for jour in jours_uniques:
        jour_label = JOURS_FR[jour.weekday()].capitalize() + f" {jour.day:02d}/{jour.month:02d}"

        en_tete = (
            '<tr style="background:#fafafa;">'
            f'<th style="padding:6px 8px;text-align:left;color:#34495e;font-size:13px;">'
            f"{jour_label}</th>"
            + "".join(
                f'<th style="padding:6px 4px;text-align:center;font-size:11px;color:#888;">'
                f"{nom}</th>"
                for nom, _, _ in FENETRES_VEILLE
            )
            + "</tr>"
        )

        def serie_fenetre(
            jour_c: pd.Timestamp, colonne: str, h_debut: int, h_fin: int
        ) -> pd.Series:
            return _serie_fenetre(horaire, jour_c, colonne, h_debut, h_fin)

        def cellule_picto(jour_courant: pd.Timestamp = jour) -> str:
            cells = []
            for _nom, h_debut, h_fin in FENETRES_VEILLE:
                if (jour_courant, h_debut) not in pleins:
                    cells.append('<td style="padding:1px 4px;text-align:center;color:#ccc;">—</td>')
                    continue
                codes = serie_fenetre(jour_courant, "weather_code", h_debut, h_fin)
                code = code_dominant_fenetre(codes) if not codes.empty else None
                if code is None:
                    cells.append('<td style="padding:1px 4px;text-align:center;color:#ccc;">—</td>')
                    continue
                # Variante nuit (lune) pour la fenêtre [0, 6).
                est_nuit = h_fin <= FENETRE_NUIT_PICTO_FIN
                uri = icone_base64(code, nuit=est_nuit)
                alt = libelle(code)
                cells.append(
                    '<td style="padding:1px 4px;text-align:center;">'
                    f'<img src="{uri}" alt="{alt}" title="{alt}" '
                    'style="width:56px;height:56px;display:block;margin:0 auto;">'
                    "</td>"
                )
            return (
                "<tr>"
                '<td style="padding:4px 8px;color:#555;font-size:13px;">Météo</td>'
                + "".join(cells)
                + "</tr>"
            )

        def ligne_indicateur(label: str, formatter, jour_courant: pd.Timestamp = jour) -> str:
            """Ligne ``<tr>`` : libellé + 4 cellules (— pour les périodes non pleines).

            ``jour_courant`` est fourni en défaut pour éviter la capture de la
            variable de boucle ``jour`` (B023).
            """
            cells = []
            for _nom, h_debut, h_fin in FENETRES_VEILLE:
                val_str = (
                    formatter(jour_courant, h_debut, h_fin)
                    if (jour_courant, h_debut) in pleins
                    else "—"
                )
                cells.append(
                    '<td style="padding:4px;text-align:center;'
                    "font-variant-numeric:tabular-nums;font-size:13px;font-weight:700;"
                    f'color:#34495e;">{val_str}</td>'
                )
            return (
                f'<tr><td style="padding:4px 8px;color:#555;font-size:13px;">{label}</td>'
                + "".join(cells)
                + "</tr>"
            )

        def fmt_t_min_max(jour_c, h_debut, h_fin) -> str:
            serie_k = serie_fenetre(jour_c, "temperature_2m", h_debut, h_fin)
            if serie_k.empty:
                return "—"
            t_min = serie_k.min() - 273.15
            t_max = serie_k.max() - 273.15
            return (
                f'<span style="color:#0072B2;">{t_min:.0f}</span>'
                f'<span style="color:#aaa;">/</span>'
                f'<span style="color:#D55E00;">{t_max:.0f}</span>'
                f"{_unite('°C')}"
            )

        def fmt_pluie(jour_c, h_debut, h_fin) -> str:
            serie = serie_fenetre(jour_c, "precipitation", h_debut, h_fin)
            if serie.empty:
                return "—"
            mm = serie.sum()
            proba = serie_fenetre(jour_c, "probabilite_pluie_pct", h_debut, h_fin)
            mm_html = f'<span style="color:#56B4E9;">{mm:.1f}</span>' + _unite("mm")
            if proba.empty:
                return mm_html
            proba_max = int(round(proba.max()))
            return (
                mm_html
                + '<span style="color:#aaa;"> / </span>'
                + f'<span style="color:#888;">{proba_max:02d}</span>'
                + _unite("%")
            )

        def fmt_vent(jour_c, h_debut, h_fin) -> str:
            vent = serie_fenetre(jour_c, "vitesse_vent_10m", h_debut, h_fin)
            rafales = serie_fenetre(jour_c, "rafales_vent_10m", h_debut, h_fin)
            if vent.empty:
                return "—"
            v_moy = vent.mean() * MS_TO_KMH_VEILLE
            r_max = (rafales.max() if not rafales.empty else vent.max()) * MS_TO_KMH_VEILLE
            return (
                f'<span style="color:#009E73;">{v_moy:.0f}</span>'
                f'<span style="color:#aaa;">/</span>'
                f'<span style="color:#E69F00;">{r_max:.0f}</span>'
                f"{_unite('km/h')}"
            )

        def fmt_hr(jour_c, h_debut, h_fin) -> str:
            serie = serie_fenetre(jour_c, "humidite_relative", h_debut, h_fin)
            if serie.empty:
                return "—"
            return f"{serie.mean() * 100:.0f}{_unite('%')}"

        def fmt_vent_direction(jour_c, h_debut, h_fin) -> str:
            sub = horaire.loc[_masque_fenetre(horaire, jour_c, h_debut, h_fin)]
            if sub.empty or "direction_vent_deg" not in sub.columns:
                return "—"
            deg = direction_dominante_vecteur(sub)
            if pd.isna(deg):
                return "—"
            cardinal = degrees_to_cardinal(deg)
            fleche = _FLECHE_DIRECTION_VENT.get(cardinal, "·")
            return (
                f'<span style="font-size:20px;color:#34495e;line-height:1;">{fleche}</span>'
                f'<span style="color:#888;font-size:11px;">&nbsp;{cardinal}</span>'
            )

        lignes = [
            en_tete,
            cellule_picto(jour),
            ligne_indicateur("T° min/max", fmt_t_min_max),
            ligne_indicateur("Pluie / proba max", fmt_pluie),
            ligne_indicateur("Vent moy / rafales", fmt_vent),
            ligne_indicateur("Vent direction", fmt_vent_direction),
            ligne_indicateur("HR moyenne", fmt_hr),
        ]

        tableaux.append(
            '<table style="width:100%;border-collapse:collapse;table-layout:fixed;'
            'margin:8px 0;border:1px solid #eee;border-radius:4px;">'
            + _GRILLE_COLGROUP
            + "".join(lignes)
            + "</table>"
        )

    return (
        '<h3 style="margin:14px 0 6px 0;font-size:15px;color:#34495e;">'
        "Tendance jusqu'à 48 h (Prévision Météo-France)</h3>" + "".join(tableaux)
    )


def composer_sujet(
    alertes: list[Alerte], maintenant: datetime, template: str, moment: str = ""
) -> str:
    """Formate le sujet selon template config.

    Variables disponibles : ``{date}`` (YYYY-MM-DD), ``{alertes_resume}``
    (ex. "gel + vent fort" ou "RAS"), ``{alertes_count}``, ``{moment}``
    ("matin"/"après-midi" — distingue les deux envois du jour).
    """
    return template.format(
        date=maintenant.strftime("%Y-%m-%d"),
        alertes_resume=resume_alertes(alertes),
        alertes_count=len(alertes),
        moment=moment,
    )


def _moment_avec_article(moment: str) -> str:
    """``"matin"`` → ``"du matin"`` ; ``"après-midi"`` → ``"de l'après-midi"``.

    Chaîne vide → vide (rétro-compat : pas de moment fourni).
    """
    if moment == "matin":
        return "du matin"
    if moment == "après-midi":
        return "de l'après-midi"
    return ""


def composer_texte(
    ind: IndicateursVeille,
    alertes: list[Alerte],
    maintenant: datetime,
    url_fiches: str = "",
    source: str = SOURCE_DEFAUT,
    cron: str = CRON_EXPLAIN,
    site: str = SITE_EXPLAIN,
    tz_locale: str = "Europe/Paris",
    moment: str = "",
    prevision_horaire: pd.DataFrame | None = None,
) -> str:
    """Corps email texte simple — fallback universel et lisible mobile."""
    article = _moment_avec_article(moment)
    lignes: list[str] = []
    titre = f"Veille {article}" if article else "Veille météo"
    lignes.append(f"{titre} — {format_date_fr(maintenant)}")
    lignes.append("=" * 70)
    if ind.prevision_t0_local is not None:
        # 1ʳᵉ période de 6 h locale affichée (heure locale, ADR-0014 D4).
        t0_loc = ind.prevision_t0_local.tz_convert(tz_locale)
        fenetre_label = f"à partir du {t0_loc.strftime('%d/%m/%Y %Hh00')}"
    else:
        fenetre_label = "—"
    lignes.append(f"Prévision {fenetre_label}")
    lignes.append("")

    lignes.append("VIGILANCE EXPLOITATION :")
    if alertes:
        for a in alertes:
            lignes.append(f"  [{a.niveau.upper()}] {a.titre}")
            lignes.append(f"      seuil configuré : {a.seuil} {a.unite}")
    else:
        lignes.append("  Aucune alerte sur les 48 h.")
    lignes.append("")

    # Tendance 48 h en mots (équivalent texte de la bande pictos HTML).
    tendance_lignes = _tendance_texte_48h(prevision_horaire, tz_locale)
    if tendance_lignes:
        lignes.append("TENDANCE 48 h (Prévision Météo-France) :")
        lignes.extend(tendance_lignes)
        lignes.append("")

    def fmt(label: str, val: str, win: str) -> str:
        return f"  {label:<22}: {val:>12}   [{win}]"

    direction = ind.direction_vent_dominante_cardinal or "—"

    lignes.append("INDICATEURS :")
    lignes.append(fmt("T° min", f"{ind.temperature_min_24h_celsius:.1f} °C", "0-24 h"))
    lignes.append(fmt("T° max", f"{ind.temperature_max_24h_celsius:.1f} °C", "0-24 h"))
    lignes.append(fmt("Cumul pluie 24 h", f"{ind.cumul_pluie_24h_mm:.1f} mm", "0-24 h"))
    lignes.append(fmt("Cumul pluie 48 h", f"{ind.cumul_pluie_48h_mm:.1f} mm", "0-48 h"))
    lignes.append(fmt("Proba. pluie 24 h", f"{ind.prob_pluie_max_24h_pct:.0f} %", "max horaire"))
    lignes.append(fmt("Proba. pluie 48 h", f"{ind.prob_pluie_max_48h_pct:.0f} %", "max horaire"))
    lignes.append(fmt("Vent moy max", f"{ind.vent_max_24h_kmh:.0f} km/h", "0-24 h"))
    lignes.append(fmt("Rafales max", f"{ind.rafales_max_24h_kmh:.0f} km/h", "0-24 h"))
    lignes.append(
        fmt(
            "Vent direction dom.",
            f"{direction} ({ind.direction_vent_dominante_deg:.0f}°)",
            "0-24 h, pondéré vitesse",
        )
    )
    lignes.append("")
    lignes.append("-" * 70)
    lignes.append("Ce mail est un signal informationnel — vous gardez la décision")
    lignes.append("(cf. principe #1 du projet).")
    lignes.append("")
    lignes.append(f"Source : {source}")
    lignes.append(f"Cron   : {cron}")
    lignes.append(f"Site   : {site}")
    if url_fiches:
        lignes.append(f"Fiches : {url_fiches}")
    return "\n".join(lignes)


def composer_html(
    ind: IndicateursVeille,
    alertes: list[Alerte],
    maintenant: datetime,
    url_fiches: str = "",
    source: str = SOURCE_DEFAUT,
    cron: str = CRON_EXPLAIN,
    site: str = SITE_EXPLAIN,
    chart_48h_base64: str = "",
    cartes_grille: CartesGrille | None = None,
    vigilance: VigilanceDepartement | None = None,
    prevision_horaire: pd.DataFrame | None = None,
    seuils_config: dict[str, Any] | None = None,
    moment: str = "",
    tz_locale: str = "Europe/Paris",
    commune: str | None = None,
) -> str:
    """Corps email HTML mobile-first (table inline, pas de framework)."""
    # ``now_utc`` pour aligner la fenêtre J0 00 h 00 → J0+48 h entre
    # la grille Tendance et le graphique. On le dérive de ``maintenant``
    # (qui peut être naïf ; on suppose UTC).
    now_utc_ts = pd.Timestamp(maintenant)
    if now_utc_ts.tzinfo is None:
        now_utc_ts = now_utc_ts.tz_localize("UTC")
    else:
        now_utc_ts = now_utc_ts.tz_convert("UTC")

    bloc_grille = _bloc_grille_indicateurs_48h(
        prevision_horaire,
        now_utc=now_utc_ts,
        tz_locale=tz_locale,
    )
    bloc_carte = _bloc_cartes_synoptiques(cartes_grille, tz_locale=tz_locale)
    bloc_vigilance = _bloc_vigilance_mf(vigilance, tz_locale=tz_locale, now=now_utc_ts)
    bloc_vigilance_exploitation = _bloc_vigilance_exploitation(alertes)
    bloc_definitions = _bloc_definitions(seuils_config)
    # Décalage UTC↔local pour la série temporelle (axe en UTC, ADR-0014).
    decalage_utc = _libelle_decalage_utc(prevision_horaire, tz_locale)
    note_horaire = (
        f"Détail horaire 48 h — UTC ({decalage_utc})"
        if decalage_utc
        else "Détail horaire 48 h — UTC"
    )

    lien_fiches = (
        f'<p style="margin:6px 0;font-size:12px;color:#888;">'
        f'Fiches indices : <a href="{url_fiches}" style="color:#888;">{url_fiches}</a></p>'
        if url_fiches
        else ""
    )

    footer = (
        '<div style="margin-top:18px;padding-top:12px;border-top:1px solid #eee;'
        'font-size:11px;color:#888;line-height:1.5;">'
        f'<div><strong style="color:#555;">Source</strong> : {source}</div>'
        f'<div><strong style="color:#555;">Cron</strong> : {cron}</div>'
        f'<div><strong style="color:#555;">Site</strong> : {site}</div>'
        f"{lien_fiches}"
        "</div>"
    )

    # Fenêtre de prévision : 1ʳᵉ période de 6 h locale affichée (ADR-0014 D4).
    # Format monospace + fond clair pour la rendre légèrement distinctive.
    if ind.prevision_t0_local is not None:
        t0_loc = ind.prevision_t0_local.tz_convert(tz_locale)
        date_html = (
            '<span style="font-family:Menlo,Consolas,monospace;font-size:0.88em;'
            'background:#f4f4f4;padding:1px 6px;border-radius:3px;color:#34495e;">'
            f"{t0_loc.strftime('%d/%m/%Y %Hh00')}"
            "</span>"
        )
    else:
        date_html = "—"
    # Titre adapté au moment d'envoi (distingue les deux mails du jour).
    article = _moment_avec_article(moment)
    titre_h2 = (
        f"Veille {article} — prévision du {date_html}" if article else f"Prévision du {date_html}"
    )

    return f"""<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta charset="utf-8">
<title>Veille météo</title>
</head><body style="margin:0;padding:0;background:#f4f4f4;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:16px;background:white;">
  <h2 style="margin:0 0 4px 0;font-size:20px;color:#2c3e50;">
    {titre_h2}
  </h2>
  <p style="margin:0 0 12px 0;font-size:13px;color:#888;">
    {commune or "Pleine-Fougères"}
  </p>
  {bloc_vigilance}
  {bloc_vigilance_exploitation}
  {bloc_grille}
  {bloc_carte}
  <h3 style="margin:16px 0 6px 0;font-size:13px;color:#888;">{note_horaire}</h3>
  {_bloc_chart(chart_48h_base64)}
  <p style="margin:16px 0 0 0;font-size:12px;color:#888;font-style:italic;">
    Ce mail est un signal informationnel — vous gardez la décision.
    Les seuils sont des défauts opérationnels, ajustables dans la config.
  </p>
  {footer}
  {bloc_definitions}
</div>
</body></html>"""


def composer_email(
    ind: IndicateursVeille,
    alertes: list[Alerte],
    config: dict[str, Any],
    maintenant: datetime,
    chart_48h_base64: str = "",
    cartes_grille: CartesGrille | None = None,
    vigilance: VigilanceDepartement | None = None,
    prevision_horaire: pd.DataFrame | None = None,
    updated_on: pd.Timestamp | None = None,
    position: dict[str, Any] | None = None,
) -> EmailComposed:
    """Compose sujet + texte + HTML à partir des indicateurs et de la config.

    ``chart_48h_base64`` (optionnel) sera embarqué dans le HTML comme image
    inline. ``cartes_grille`` (optionnel) — Met Office + AROME synoptiques. Si
    ``None`` ou cartes toutes indisponibles, aucun bloc carte n'est rendu.
    ``updated_on`` (tz-aware UTC) — heure d'émission de la prévision officielle MF
    pour le label « Source » (ADR-0014 D1/D9) ; ``None`` retombe sur le label MF
    générique.
    """
    email_cfg = config["email"]
    url_fiches = email_cfg.get("url_fiches_indices", "") or ""
    # ADR-0014 : tout en heure locale ; source = prévision officielle MF étiquetée
    # par sa fraîcheur (updated_on).
    tz_locale = config.get("site", {}).get("tz", "Europe/Paris")
    source = label_source_mf(updated_on, tz_locale)
    # Lieu = commune réellement renvoyée par MF (point le plus proche, ADR-0014),
    # pas l'adresse de l'exploitation : la prévi vaut pour ce point.
    pos = position or {}
    commune = pos.get("name")
    if commune and pos.get("lat") is not None and pos.get("lon") is not None:
        lon = pos["lon"]
        site = (
            f"{commune} — {pos['lat']:.4f} N, {abs(lon):.4f} "
            f"{'E' if lon >= 0 else 'O'}, alt {pos.get('alti', '?')} m "
            "(point Météo-France le plus proche)"
        )
    else:
        site = commune or SITE_EXPLAIN
    now_utc_ts = pd.Timestamp(maintenant)
    now_utc_ts = (
        now_utc_ts.tz_localize("UTC") if now_utc_ts.tzinfo is None else now_utc_ts.tz_convert("UTC")
    )
    # Moment d'envoi (matin / après-midi) = heure locale (cron 6h30/18h30, D4).
    moment = moment_envoi(now_utc_ts, tz_locale)
    sujet = composer_sujet(alertes, maintenant, email_cfg["sujet_template"], moment=moment)
    texte = composer_texte(
        ind,
        alertes,
        maintenant,
        url_fiches=url_fiches,
        source=source,
        site=site,
        moment=moment,
        tz_locale=tz_locale,
        prevision_horaire=prevision_horaire,
    )
    alertes_config = config.get("alertes", {})
    html = composer_html(
        ind,
        alertes,
        maintenant,
        url_fiches=url_fiches,
        source=source,
        site=site,
        commune=commune,
        chart_48h_base64=chart_48h_base64,
        cartes_grille=cartes_grille,
        vigilance=vigilance,
        prevision_horaire=prevision_horaire,
        seuils_config=alertes_config,
        moment=moment,
        tz_locale=tz_locale,
    )
    return EmailComposed(sujet=sujet, texte=texte, html=html)
