"""Composition de l'email matinal Veille (texte + HTML mobile-first).

Génère sujet, corps texte (fallback) et corps HTML responsive à partir
des indicateurs et alertes calculés.

Le ton reste informationnel (cf. principe n°1). L'utilisateur garde
son jugement empirique pour décider.

Le titre porte la **fraîcheur officielle MF** (``updated_on``) et le footer
rappelle la **source** (principe n°5 transparence). Cf. ADR-0014.

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

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from apps.operationnelle.cartes_geo import (
    METEOCIEL_PAGE_AFFICHEE as ARPEGE_EUR_PAGE_AFFICHEE,
)

# Helpers FR partagés avec App 2 Opérationnelle, cf. apps/shared/dates_fr.py.
from apps.shared.dates_fr import (
    JOURS_FR,
    MOIS_FR,
    format_date_fr,
    format_horodatage_fr,
    format_t0_court,
)
from meteo_socle.sources.dpvigilance import (
    NIVEAU_NOMS as VIGILANCE_NIVEAU_NOMS,
)
from meteo_socle.sources.dpvigilance import (
    VigilanceDepartementDP,
)
from meteo_socle.sources.meteofrance_phealth import UVJournalier, libelle_uv_oms
from meteo_socle.sources.vigieau import LABELS_NIVEAU, NIVEAU_AUCUNE, RestrictionsEau

from .alertes import Alerte, resume_alertes
from .anomalies import Anomalie, bloc_rapport_bug
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

logger = logging.getLogger(__name__)

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


def _format_fenetre_vigilance(debut: pd.Timestamp, fin: pd.Timestamp, tz_locale: str) -> str:
    """Fenêtre horodatée en heure locale : ``jeu. 14h–22h`` (``…–ven. 02h`` si à cheval)."""
    d = debut.tz_convert(tz_locale)
    f = fin.tz_convert(tz_locale)

    def hh(x: pd.Timestamp) -> str:
        return x.strftime("%Hh%M") if x.minute else x.strftime("%Hh")

    jour_d = JOURS_FR[d.weekday()][:3] + "."
    if d.date() == f.date():
        return f"{jour_d} {hh(d)}–{hh(f)}"
    jour_f = JOURS_FR[f.weekday()][:3] + "."
    return f"{jour_d} {hh(d)}–{jour_f} {hh(f)}"


def _periodes_vigilance(phenomene: object, tz_locale: str) -> str:
    """Fenêtres horodatées (au niveau affiché) d'un phénomène, fusionnées et jointes.

    Lit les ``tranches`` DPVigilance (``begin_time``/``end_time`` UTC). Fusionne les
    segments contigus/chevauchants — MF découpe parfois heure par heure — avant le
    rendu. Vide si aucune tranche (source sans découpage temporel) → le bloc retombe
    sur le seul niveau, rétro-compatible.
    """
    tranches = getattr(phenomene, "tranches", None) or []
    niveau = phenomene.niveau  # type: ignore[attr-defined]
    pertinentes = sorted((t for t in tranches if t.niveau >= niveau), key=lambda t: t.debut)
    fenetres: list[list[pd.Timestamp]] = []
    for t in pertinentes:
        if fenetres and t.debut <= fenetres[-1][1]:
            fenetres[-1][1] = max(fenetres[-1][1], t.fin)
        else:
            fenetres.append([t.debut, t.fin])
    return ", ".join(_format_fenetre_vigilance(d, f, tz_locale) for d, f in fenetres)


def _bloc_vigilance_mf(
    vigilance: VigilanceDepartementDP | None,
    tz_locale: str = "Europe/Paris",
    now: pd.Timestamp | None = None,
) -> str:
    """Bloc HTML Vigilance Météo-France (webservice, ADR-0014).

    - ``None`` (fetch échoué) → bloc vide.
    - Tout vert → ligne compacte "rien à signaler".
    - ≥ 1 phénomène ≥ jaune → mini-tableau des phénomènes non-verts + niveau, avec
      la/les **fenêtre(s) horodatée(s)** sous le nom (DPVigilance est horodatée J/J+1).

    Vigilance officielle d'État. Référence légale pour les phénomènes dangereux
    (« une seule méthode par phénomène »). Source DPVigilance (ADR-0021) : niveau max
    par phénomène + tranches ``begin_time``/``end_time`` (mêmes tranches que l'overlay
    picto orage). Une source sans découpage (tranches absentes) n'affiche que le niveau.
    """
    if vigilance is None:
        return ""

    validite = ""
    if vigilance.fin_validite is not None:
        fin_loc = vigilance.fin_validite.tz_convert(tz_locale)
        validite = f"valide jusqu'au {fin_loc.strftime('%d/%m %Hh%M %Z')} · "
    # `update_time` peut manquer (DPVigilance sans meta) → on omet la fraîcheur.
    maj = ""
    if vigilance.update_time is not None:
        update_loc = vigilance.update_time.tz_convert(tz_locale)
        maj = f"mise à jour {update_loc.strftime('%d/%m %Hh%M %Z')}"
    legende = (
        f'<a href="{VIGILANCE_URL_AFFICHEE}" '
        'style="color:#888;text-decoration:underline;">Vigilance Météo-France</a> · '
        f"dépt {vigilance.departement} · {validite}{maj}"
    )
    # Fraîcheur (ADR-0014 D10) : carte plus vieille que ~12 h → l'actualisation du
    # cycle courant (6 h/16 h locales) n'est pas encore publiée. On le signale,
    # sans retry (si systématique, retarder le cron).
    if (
        now is not None
        and vigilance.update_time is not None
        and (now - vigilance.update_time) > VIGILANCE_AGE_MAX
    ):
        legende += (
            '<br><span style="color:#a04000;">⚠ Actualisation du cycle non encore publiée</span>'
        )

    titre = '<h3 style="margin:0 0 6px 0;font-size:15px;color:#34495e;">Vigilance Météo-France</h3>'

    # Tous verts : ligne compacte "rien à signaler" (le dépt est dans la légende,
    # pas de redondance).
    if vigilance.niveau_max_global <= 1:
        return (
            '<div style="margin:12px 0 6px 0;">' + titre + '<div style="padding:8px 12px;'
            'background:#f4f4f4;border-radius:4px;font-size:12px;color:#555;">'
            "Aucune vigilance en cours."
            f'<div style="font-size:11px;color:#888;margin-top:4px;">{legende}</div>'
            "</div></div>"
        )

    # Filtre phénomènes non-verts pour réduire le bruit.
    actifs = [p for p in vigilance.phenomenes if p.niveau > 1]

    def cellule_niveau(niveau: int) -> str:
        c = _VIGILANCE_COULEURS.get(niveau, _VIGILANCE_COULEURS[1])
        return (
            f'<td style="padding:4px 8px;text-align:center;'
            f"background:{c['bg']};color:{c['fg']};font-weight:600;"
            'font-size:12px;border:1px solid #fff;">'
            f"{VIGILANCE_NIVEAU_NOMS[niveau]}"
            "</td>"
        )

    # Colonne Horizon : la/les fenêtre(s) horodatée(s) DPVigilance (J/J+1) — l'info
    # qu'on utilise déjà pour le picto orage. « — » si la source n'est pas horodatée.
    lignes_html = []
    for p in actifs:
        periodes = _periodes_vigilance(p, tz_locale) or "—"
        lignes_html.append(
            "<tr>"
            f'<td style="padding:4px 8px;color:#555;font-size:12px;">{p.nom}</td>'
            + cellule_niveau(p.niveau)
            + '<td style="padding:4px 8px;color:#555;font-size:12px;'
            f'text-align:right;white-space:nowrap;">{periodes}</td>' + "</tr>"
        )

    return (
        '<div style="margin:12px 0 6px 0;">' + titre + '<table cellpadding="0" cellspacing="0" '
        'border="0" style="width:100%;border-collapse:collapse;'
        'border:1px solid #eee;border-radius:4px;overflow:hidden;">'
        '<tr style="background:#fafafa;">'
        '<th style="padding:6px 8px;text-align:left;font-size:11px;color:#888;'
        'font-weight:600;">Phénomène</th>'
        '<th style="padding:6px 8px;text-align:center;font-size:11px;color:#888;'
        'font-weight:600;">Niveau</th>'
        '<th style="padding:6px 8px;text-align:right;font-size:11px;color:#888;'
        'font-weight:600;">Horizon</th>'
        "</tr>" + "".join(lignes_html) + "</table>"
        f'<p style="margin:4px 0 0 0;font-size:11px;color:#888;">{legende}</p>'
        "</div>"
    )


_VIGIEAU_URL_BASE = "https://vigieau.gouv.fr/situation"
_VIGIEAU_URL_FALLBACK = "https://vigieau.gouv.fr"

# Couleurs par niveau VigiEau (cohérentes avec la palette Bang Wong).
_VIGIEAU_COULEURS: dict[str, dict[str, str]] = {
    "vigilance": {"bg": "#fff4d1", "fg": "#9a7000"},
    "alerte": {"bg": "#ffd9b3", "fg": "#a04000"},
    "alerte_renforcee": {"bg": "#ffcccc", "fg": "#a00000"},
    "crise": {"bg": "#cc0000", "fg": "#ffffff"},
}


def _bloc_restrictions_eau(restrictions: RestrictionsEau | None, adresse_site: str = "") -> str:
    """Bloc HTML restrictions sécheresse VigiEau (conditionnel).

    Affiché uniquement quand un niveau ≥ vigilance est actif sur la zone
    souterraine (forage). Compact : niveau SOU + usage cultures spéciales
    (maraîchage, annexe 3) + date arrêté + lien vigieau.gouv.fr.
    """
    if restrictions is None or restrictions.niveau_souterrain == NIVEAU_AUCUNE:
        return ""

    niveau = restrictions.niveau_souterrain
    couleurs = _VIGIEAU_COULEURS.get(niveau, _VIGIEAU_COULEURS["alerte"])
    label_niveau = LABELS_NIVEAU.get(niveau, niveau)

    zones_sou = [z for z in restrictions.zones if z.type_ressource == "SOU"]

    # Date de l'arrêté (première zone SOU qui en a une).
    date_debut = next((z.date_debut_arrete for z in zones_sou if z.date_debut_arrete), None)
    if date_debut:
        try:
            d = pd.Timestamp(date_debut)
            date_str = f"depuis le {d.day:02d}/{d.month:02d}/{d.year}"
        except Exception:
            date_str = f"depuis le {date_debut}"
    else:
        date_str = ""

    # Dédupliquer les usages de toutes les zones SOU.
    all_usages: list = []
    for z in zones_sou:
        for u in z.usages_irrigation:
            if u not in all_usages:
                all_usages.append(u)

    # Filtre : cultures spéciales (maraîchage, annexe 3) en priorité.
    # Exclure les variantes "ressource autres" (eaux usées, eaux de pluie) et "serres".
    usages_pertinents = [u for u in all_usages if "cultures spéciales" in u.nom.lower()]
    if not usages_pertinents:
        usages_pertinents = [
            u for u in all_usages if "autres types" in u.nom.lower() and "(ressource" not in u.nom
        ]

    lignes_usages = ""
    for u in usages_pertinents:
        desc = u.description.split("\n")[0].strip()
        if len(desc) > 120:
            desc = desc[:117] + "…"
        lignes_usages += f'<li style="margin:2px 0;font-size:12px;color:#555;">{escape(desc)}</li>'

    usages_html = (
        f'<ul style="margin:6px 0 0 0;padding-left:16px;">{lignes_usages}</ul>'
        if lignes_usages
        else ""
    )

    sous_titre = (
        f' <span style="font-size:11px;font-weight:400;">{escape(date_str)}</span>'
        if date_str
        else ""
    )

    if adresse_site:
        from urllib.parse import urlencode

        url_vigieau = (
            _VIGIEAU_URL_BASE
            + "?"
            + urlencode({"profil": "entreprise", "typeEau": "SOU", "adresse": adresse_site})
        )
    else:
        url_vigieau = _VIGIEAU_URL_FALLBACK
    legende = (
        f'<a href="{url_vigieau}" '
        'style="color:#888;text-decoration:underline;">VigiEau</a>'
        f" · irrigation cultures spéciales (maraîchage) · forage"
    )

    return (
        '<div style="margin:12px 0 6px 0;">'
        '<h3 style="margin:0 0 6px 0;font-size:15px;color:#34495e;">'
        "Restrictions sécheresse</h3>"
        '<div style="padding:8px 12px;border-radius:4px;'
        f'background:{couleurs["bg"]};border-left:4px solid {couleurs["fg"]};">'
        '<span style="font-size:13px;font-weight:700;'
        f'color:{couleurs["fg"]};">{escape(label_niveau)}</span>{sous_titre}'
        f"{usages_html}"
        f'<div style="font-size:11px;color:#888;margin-top:6px;">{legende}</div>'
        "</div>"
        "</div>"
    )


def _format_dt_court_fr(dt: pd.Timestamp) -> str:
    """Formate un instant en français court : ``lun. 01/06 08 h``."""
    jour_court = JOURS_FR[dt.weekday()][:3] + "."
    return f"{jour_court} {dt.day:02d}/{dt.month:02d} {dt.hour:02d} h"


def _bloc_cartes_synoptiques(
    grille: CartesGrille | None,
    tz_locale: str = "Europe/Paris",
    cartes_longue: Any = None,
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
    cartes_longue_dispo = [
        c for c in (getattr(cartes_longue, "cartes", None) or []) if getattr(c, "data_uri", "")
    ]
    nb_synoptique = grille.nb_disponibles if grille is not None else 0
    if nb_synoptique == 0 and not cartes_longue_dispo:
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
            # Juste la date/heure (en gras dans la carte) : la date EST l'échéance,
            # pas besoin du préfixe « Échéance : ». Heure locale, cohérente avec le
            # sous-titre « (heure locale) » — surtout pas « UTC » (fausse étiquette).
            cible_label = _format_dt_court_fr(cible_loc)
            if not c.data_uri:
                motif = getattr(c, "motif_indispo", "") or "indisponible"
                lignes.append(
                    '<p style="text-align:center;color:#bbb;font-size:11px;'
                    f'margin:6px 0;">{cible_label} — carte indisponible ({motif})</p>'
                )
                continue
            lignes.append(
                '<div style="text-align:center;margin:6px 0 10px 0;">'
                # Échéance bien visible (la cible de la carte) : plus grande, grasse,
                # sombre — à ne pas confondre avec le sous-titre « Run … » discret.
                '<div style="font-size:13px;color:#2c3e50;font-weight:700;margin-bottom:2px;">'
                f"{cible_label}"
                "</div>"
                f'<img src="{c.data_uri}" alt="{alt_prefix} — {cible_label}" '
                'style="max-width:100%;height:auto;border-radius:4px;'
                'border:1px solid #eee;">'
                "</div>"
            )
        return "".join(lignes)

    section_metoffice = cartes_section(
        grille.metoffice if grille is not None else [],
        titre="Met Office UK — surface (Atlantique nord / Europe, fronts)",
        source_url=METOFFICE_PAGE_AFFICHEE,
        alt_prefix="Met Office surface",
    )
    section_arome = cartes_section(
        grille.arome if grille is not None else [],
        titre="Météociel AROME 1.3 km — France (précip + pression + nébulosité)",
        source_url=METEOCIEL_PAGE_AFFICHEE,
        alt_prefix="AROME résumé France",
        run_suffixe=" (veille)",
    )
    # Prolongement moyen terme : ARPEGE-Europe J+3 / J+4, dans la même série
    # synoptique (cf. demande de regroupement de toutes les cartes).
    section_arpege = cartes_section(
        cartes_longue_dispo,
        titre="Météociel ARPEGE-Europe ~10 km — moyen terme (J+3 / J+4)",
        source_url=ARPEGE_EUR_PAGE_AFFICHEE,
        alt_prefix="ARPEGE-Europe résumé",
    )

    return (
        '<div style="margin:18px 0 6px 0;">'
        '<h2 style="margin:18px 0 8px 0;font-size:17px;color:#2c3e50;'
        'border-bottom:2px solid #eee;padding-bottom:4px;">'
        "Situation synoptique</h2>"
        f"{section_metoffice}"
        f"{section_arome}"
        f"{section_arpege}"
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

# Choix du picto : la variante nuit (lune au lieu du soleil) est utilisée
# pour les fenêtres "Nuit" [0, 6) et "Soir" [18, 24) — cohérent avec MF.com
# qui affiche la lune dès la soirée. Les icônes yr sans variante nuit (orage,
# couvert, pluie continue…) retombent sur l'icône jour/neutre, qui reste lisible.
FENETRE_NUIT_PICTO_FIN = 6  # borne haute de la fenêtre "Nuit"
FENETRE_SOIR_DEBUT = 18  # borne basse de la fenêtre "Soir"

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
    "NE": "↙︎",  # VS-15 : force rendu texte (sinon emoji fond bleu sur Android)
    "E": "←",
    "SE": "↖︎",
    "S": "↑",
    "SO": "↗︎",
    "O": "→",
    "NO": "↘︎",
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


def _stat_pct(sub: pd.DataFrame, colonne: str) -> str:
    """``moyenne/max`` en % d'une colonne fraction (0-1) sur une tranche (``n/d`` si absente)."""
    if colonne not in sub.columns:
        return "n/d"
    s = sub[colonne].dropna()
    return "n/d" if s.empty else f"{s.mean() * 100:.0f}/{s.max() * 100:.0f}"


def _log_diagnostic_pictos(
    horaire_loc: pd.DataFrame,
    jours_uniques: list[pd.Timestamp],
    pleins: set[tuple[pd.Timestamp, int]],
) -> None:
    """Log INFO par tranche affichée → calibration picto vs MF.com (``docs/calibration_pictos.md``).

    Émet, par tranche 6 h, la **nébulosité** totale/basse/moyenne (moyenne **et** max
    sur les heures de la tranche, en %), le cumul de pluie et les **codes OMM horaires**
    — l'info qui manque pour départager « agrégation max trop pessimiste » vs « AROME
    vraiment couvert ». Visible dans le log du workflow (jamais dans le mail).
    """
    if not logger.isEnabledFor(logging.INFO):
        return
    for jour in jours_uniques:
        for nom, h_debut, h_fin in FENETRES_VEILLE:
            if (jour, h_debut) not in pleins:
                continue
            sub = horaire_loc.loc[_masque_fenetre(horaire_loc, jour, h_debut, h_fin)]
            if sub.empty:
                continue
            pr = sub["precipitation"] if "precipitation" in sub.columns else None
            pluie = float(pr.sum()) if pr is not None else float("nan")
            codes = (
                sub["weather_code"].dropna().astype(int).tolist()
                if "weather_code" in sub.columns
                else []
            )
            jour_lbl = JOURS_FR[jour.weekday()][:3] + f". {jour.day:02d}/{jour.month:02d}"
            logger.info(
                "PICTO-DIAG %s %-11s | nébul tot %s bas %s moy %s (moy/max %%) "
                "| pluie %.1f mm | codes %s",
                jour_lbl,
                nom,
                _stat_pct(sub, "cloud_cover"),
                _stat_pct(sub, "cloud_cover_low"),
                _stat_pct(sub, "cloud_cover_mid"),
                pluie,
                codes,
            )


def _val_frac_pct(row: pd.Series, col: str) -> float | None:
    """Colonne fraction (0-1) → %, arrondie à 1 décimale ; None si absente/NaN."""
    if col not in row.index or pd.isna(row[col]):
        return None
    return round(float(row[col]) * 100.0, 1)


def _val_num(row: pd.Series, col: str, scale: float = 1.0) -> float | None:
    """Colonne numérique → float×scale, arrondi à 2 déc. ; None si absente/NaN."""
    if col not in row.index or pd.isna(row[col]):
        return None
    return round(float(row[col]) * scale, 2)


def _log_hora_diag(
    horaire_loc: pd.DataFrame,
    jours_uniques: list[pd.Timestamp],
    pleins: set[tuple[pd.Timestamp, int]],
) -> None:
    """Log horaire JSON pour le dataset ML (``HORA-DIAG``).

    Une ligne structurée par heure de chaque tranche affichée — inputs AROME bruts
    (cloud_cover %, précip mm, temp °C, ptype, visi m, HR) + code WMO dérivé.
    Parsé par ``calibration/collect.py`` pour construire ``data/calibration/dataset.csv``.
    Couvre tous les cas (hiver inclus) : temp/ptype/visi sont ``null`` si absents,
    pas NaN, pour rester valides en JSON.
    """
    if not logger.isEnabledFor(logging.INFO):
        return
    for jour in jours_uniques:
        jour_str = jour.strftime("%Y-%m-%d")
        for nom, h_debut, h_fin in FENETRES_VEILLE:
            if (jour, h_debut) not in pleins:
                continue
            sub = horaire_loc.loc[_masque_fenetre(horaire_loc, jour, h_debut, h_fin)]
            if sub.empty:
                continue
            for ts_loc, row in sub.iterrows():
                ts_utc = ts_loc.tz_convert("UTC").strftime("%Y-%m-%dT%H:%MZ")
                temp_c: float | None = None
                if "temperature_2m" in row.index and not pd.isna(row["temperature_2m"]):
                    temp_c = round(float(row["temperature_2m"]) - 273.15, 1)
                ptype: int | None = None
                if "type_precip" in row.index and not pd.isna(row["type_precip"]):
                    ptype = int(row["type_precip"])
                wmo: int | None = None
                if "weather_code" in row.index and not pd.isna(row["weather_code"]):
                    wmo = int(row["weather_code"])
                record = {
                    "tranche": nom,
                    "jour": jour_str,
                    "cc": _val_frac_pct(row, "cloud_cover"),
                    "cc_low": _val_frac_pct(row, "cloud_cover_low"),
                    "cc_mid": _val_frac_pct(row, "cloud_cover_mid"),
                    "precip": _val_num(row, "precipitation"),
                    "temp_c": temp_c,
                    "ptype": ptype,
                    "visi_m": _val_num(row, "visibilite_m"),
                    "humi": _val_num(row, "humidite_relative"),
                    "wmo": wmo,
                }
                logger.info("HORA-DIAG %s %s", ts_utc, json.dumps(record, ensure_ascii=False))


def _bloc_grille_indicateurs_48h(
    prevision_horaire: pd.DataFrame | None,
    now_utc: pd.Timestamp | None = None,
    tz_locale: str = "Europe/Paris",
    uv_journalier: UVJournalier | None = None,
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

    # Horizon = soir de J+1 (demain local). On ne montre PAS J+2, même quand AROME
    # le fournit (l'après-midi, le run atteint J+2 matin) : la Vigilance ne couvre que
    # J/J+1 (DPVigilance, ADR-0021) → le picto orage y serait structurellement aveugle,
    # et la section « La semaine » prend déjà le relais au-delà. Cap au RENDU seulement
    # (les indicateurs gardent les 48 h pleines). Sans ``apres`` (tests) → pas de cap.
    if apres is not None:
        dernier_jour = apres.normalize() + pd.Timedelta(days=1)
        periodes = [p for p in periodes if p[1].normalize() <= dernier_jour]
        if not periodes:
            return ""

    # Périodes pleines à afficher : clé (jour local normalisé, heure de début).
    pleins = {(debut.normalize(), debut.hour) for _, debut, _ in periodes}
    jours_uniques = sorted({debut.normalize() for _, debut, _ in periodes})
    _log_diagnostic_pictos(horaire, jours_uniques, pleins)  # calibration picto (log CI)
    _log_hora_diag(horaire, jours_uniques, pleins)  # dataset ML (log CI)
    tableaux: list[str] = []

    for jour_idx, jour in enumerate(jours_uniques):
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
                # Variante nuit (lune) pour Nuit [0, 6) et Soir [18, 24).
                est_nuit = h_fin <= FENETRE_NUIT_PICTO_FIN or h_debut >= FENETRE_SOIR_DEBUT
                uri = icone_base64(code, nuit=est_nuit)
                alt = libelle(code)
                cells.append(
                    '<td style="padding:1px 4px;text-align:center;">'
                    f'<img src="{uri}" alt="{alt}" title="{alt}" '
                    'style="width:45px;height:45px;display:block;margin:0 auto;">'
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

        def fmt_t_ressenti(jour_c, h_debut, h_fin) -> str:
            from meteo_socle.indices.temperature_ressentie import temperature_ressentie_serie

            serie_k = serie_fenetre(jour_c, "temperature_2m", h_debut, h_fin)
            if serie_k.empty:
                return "—"
            serie_v = serie_fenetre(jour_c, "vitesse_vent_10m", h_debut, h_fin)
            serie_hr = serie_fenetre(jour_c, "humidite_relative", h_debut, h_fin)
            if serie_v.empty and serie_hr.empty:
                return "—"
            temp_c = serie_k - 273.15
            v_ms = (
                serie_v.reindex(temp_c.index)
                if not serie_v.empty
                else pd.Series(float("nan"), index=temp_c.index)
            )
            hr = (
                serie_hr.reindex(temp_c.index)
                if not serie_hr.empty
                else pd.Series(float("nan"), index=temp_c.index)
            )
            ressenti = temperature_ressentie_serie(temp_c, v_ms, hr)
            t_min = ressenti.min()
            t_max = ressenti.max()
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

        uvi_journee = float("nan")
        if uv_journalier is not None:
            uvi_journee = uv_journalier.uvi_j0 if jour_idx == 0 else uv_journalier.uvi_j1

        import math

        def _ligne_uv_jour(uvi: float) -> str:
            if math.isnan(uvi):
                return ""
            if round(uvi) <= 2:  # Faible : pas de protection nécessaire → on n'affiche pas
                return ""
            label, couleur = libelle_uv_oms(uvi)
            return (
                '<tr><td style="padding:4px 8px;color:#555;font-size:13px;">Indice UV (jour)</td>'
                '<td colspan="4" style="text-align:center;padding:4px;'
                'font-size:13px;font-weight:700;">'
                f'<span style="color:{couleur};">{uvi:.1f}</span>'
                f'<span style="color:#888;"> ({label})</span>'
                "</td></tr>"
            )

        lignes = [
            en_tete,
            cellule_picto(jour),
            ligne_indicateur("T° min/max", fmt_t_min_max),
            ligne_indicateur("T° ressentie min/max", fmt_t_ressenti),
            ligne_indicateur("Pluie / proba max", fmt_pluie),
            ligne_indicateur("Vent moy / rafales", fmt_vent),
            ligne_indicateur("Vent direction", fmt_vent_direction),
            ligne_indicateur("HR moyenne", fmt_hr),
        ]
        uv_html = _ligne_uv_jour(uvi_journee)
        if uv_html:
            lignes.append(uv_html)

        tableaux.append(
            '<table style="width:100%;border-collapse:collapse;table-layout:fixed;'
            'margin:8px 0;border:1px solid #eee;border-radius:4px;">'
            + _GRILLE_COLGROUP
            + "".join(lignes)
            + "</table>"
        )

    return (
        '<h3 style="margin:14px 0 6px 0;font-size:15px;color:#34495e;">'
        "Tendance jusqu'à 48 h</h3>" + "".join(tableaux)
    )


def _titre_mail(maintenant: datetime, moment: str = "", tz_locale: str = "Europe/Paris") -> str:
    """Titre commun au sujet, au titre HTML et au corps texte.

    « Météo du <jour J/MM> » (date locale), suffixé « <moment> »
    quand l'envoi distingue matin / après-midi. Source unique pour que le
    sujet du mail et son titre affiché soient alignés.
    """
    mnt = pd.Timestamp(maintenant)
    mnt = mnt.tz_localize("UTC") if mnt.tzinfo is None else mnt.tz_convert("UTC")
    mnt_loc = mnt.tz_convert(tz_locale)
    date_str = f"{JOURS_FR[mnt_loc.weekday()]} {mnt_loc.day}/{mnt_loc.month:02d}"
    return f"Météo du {date_str}" + (f" {moment}" if moment else "")


def resume_vigilance_mf(vigilance: VigilanceDepartementDP | None) -> str:
    """Résumé court de la Vigilance MF d'État pour le sujet du mail.

    Ex. « Vigilance orange : Orages » (phénomènes au pire niveau) ; « RAS » si
    aucune vigilance (tout vert ou indisponible).
    """
    if vigilance is None or vigilance.niveau_max_global <= 1:
        return "RAS"
    niveau = vigilance.niveau_max_global
    noms = ", ".join(p.nom for p in vigilance.phenomenes if p.niveau == niveau)
    return f"Vigilance {VIGILANCE_NIVEAU_NOMS[niveau].lower()} : {noms}"


def composer_sujet(
    alertes: list[Alerte],
    maintenant: datetime,
    template: str,
    moment: str = "",
    tz_locale: str = "Europe/Paris",
    vigilance: VigilanceDepartementDP | None = None,
) -> str:
    """Formate le sujet selon template config.

    Variables disponibles : ``{titre}`` (titre identique au contenu, ex.
    "Météo du samedi 7/06 après-midi"), ``{vigilance_resume}`` (Vigilance MF
    d'État, ex. "Vigilance orange : Orages" ou "RAS"), ``{alertes_resume}``
    (ancien résumé d'alertes exploitation), ``{date}`` (YYYY-MM-DD),
    ``{alertes_count}``, ``{moment}`` ("matin"/"après-midi").

    Le template par défaut ``"{titre} — {vigilance_resume}"`` aligne le sujet
    sur le titre affiché, suffixé du niveau de Vigilance d'État.
    """
    return template.format(
        titre=_titre_mail(maintenant, moment, tz_locale),
        date=maintenant.strftime("%Y-%m-%d"),
        alertes_resume=resume_alertes(alertes),
        alertes_count=len(alertes),
        moment=moment,
        vigilance_resume=resume_vigilance_mf(vigilance),
    )


def composer_texte(
    ind: IndicateursVeille | None,
    alertes: list[Alerte],
    maintenant: datetime,
    tz_locale: str = "Europe/Paris",
    moment: str = "",
    prevision_horaire: pd.DataFrame | None = None,
    updated_on: pd.Timestamp | None = None,
    bloc_semaine_texte: str = "",
) -> str:
    """Corps email texte simple — fallback universel et lisible mobile.

    ``ind`` à ``None`` (webservice MF injoignable au dernier essai) → la partie
    48 h est omise : on l'indique en une ligne et le corps se réduit à la section
    semaine. ``bloc_semaine_texte`` (optionnel) — équivalent texte de la section
    semaine, ajouté en fin de corps (mail matinal uniquement).
    """
    lignes: list[str] = []
    lignes.append(_titre_mail(maintenant, moment, tz_locale))
    lignes.append("=" * 70)
    if ind is None:
        # Pas de repli inventé : on omet la 48 h et on le dit. La tendance des
        # prochains jours (section semaine ci-dessous) porte l'essentiel.
        lignes.append("PRÉVISION 48 h MÉTÉO-FRANCE INDISPONIBLE")
        lignes.append("  (partie omise — voir la tendance des prochains jours ci-dessous)")
    else:
        lignes.append("PRÉVISION MÉTÉO-FRANCE — MODÈLE AROME (picto dérivé)")
        if updated_on is not None:
            maj = updated_on.tz_convert(tz_locale).strftime("%d/%m %Hh%M %Z")
            lignes.append(f"  Mise à jour {maj}")
        lignes.append("")

        # Tendance 48 h en mots (équivalent texte de la bande pictos HTML).
        tendance_lignes = _tendance_texte_48h(prevision_horaire, tz_locale)
        if tendance_lignes:
            lignes.append("TENDANCE 48 h :")
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
        lignes.append(
            fmt("Proba. pluie 24 h", f"{ind.prob_pluie_max_24h_pct:.0f} %", "max horaire")
        )
        lignes.append(
            fmt("Proba. pluie 48 h", f"{ind.prob_pluie_max_48h_pct:.0f} %", "max horaire")
        )
        lignes.append(fmt("Vent moy max", f"{ind.vent_max_24h_kmh:.0f} km/h", "0-24 h"))
        lignes.append(fmt("Rafales max", f"{ind.rafales_max_24h_kmh:.0f} km/h", "0-24 h"))
        lignes.append(
            fmt(
                "Vent direction dom.",
                f"{direction} ({ind.direction_vent_dominante_deg:.0f}°)",
                "0-24 h, pondéré vitesse",
            )
        )
    if bloc_semaine_texte:
        lignes.append(bloc_semaine_texte)
    return "\n".join(lignes)


def composer_html(
    ind: IndicateursVeille | None,
    alertes: list[Alerte],
    maintenant: datetime,
    chart_48h_base64: str = "",
    cartes_grille: CartesGrille | None = None,
    vigilance: VigilanceDepartementDP | None = None,
    prevision_horaire: pd.DataFrame | None = None,
    seuils_config: dict[str, Any] | None = None,
    moment: str = "",
    tz_locale: str = "Europe/Paris",
    commune: str | None = None,
    updated_on: pd.Timestamp | None = None,
    bloc_guides_tendance: str = "",
    bloc_sources_semaine: str = "",
    cartes_longue: Any = None,
    lieu: str | None = None,
    anomalies: list[Anomalie] | None = None,
    uv_journalier: UVJournalier | None = None,
    restrictions_eau: RestrictionsEau | None = None,
    adresse_site: str = "",
) -> str:
    """Corps email HTML mobile-first (table inline, pas de framework).

    Ordre : titre (avec ``lieu`` général) · prévision MF (``commune`` = point de
    grille MF, spécifique à la section) · Vigilances · grille 48 h · détail
    horaire · **La semaine** (``bloc_guides_tendance``) · **Situation synoptique**
    (Met Office + AROME + ARPEGE ``cartes_longue``, toutes les cartes regroupées)
    · sources semaine · seuils exploitation (bas, valables 48 h + semaine).

    Les blocs semaine sont vides l'après-midi → mail 48 h seul. À l'inverse, si
    ``prevision_horaire`` est ``None`` (webservice MF injoignable au dernier essai)
    la **partie 48 h est entièrement omise** (pas de section, pas de grille, pas de
    repli inventé) → mail « La semaine » seule, l'omission étant tracée au rapport
    de bug.
    """
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
        uv_journalier=uv_journalier,
    )
    bloc_carte = _bloc_cartes_synoptiques(
        cartes_grille, tz_locale=tz_locale, cartes_longue=cartes_longue
    )
    bloc_vigilance = _bloc_vigilance_mf(vigilance, tz_locale=tz_locale, now=now_utc_ts)
    bloc_restrictions = _bloc_restrictions_eau(restrictions_eau, adresse_site=adresse_site)

    # Titre neutre : le mail agrège 3 sources (prévi MF, Vigilance MF, cartes
    # synoptiques tierces) → pas de « prévision MF » dans le titre. La source est
    # précisée par section (en-têtes), pas dans un footer.
    titre_h2 = _titre_mail(maintenant, moment, tz_locale)

    # Sous-titre de la section MF : point de grille MF (commune renvoyée, ex.
    # « Sains ») — spécifique à CETTE section, pas au mail entier — + fraîcheur.
    maj_parts: list[str] = []
    if commune:
        maj_parts.append(f"point le plus proche : {commune}")
    if updated_on is not None:
        maj_loc = updated_on.tz_convert(tz_locale)
        maj_parts.append(f"Mise à jour {maj_loc.strftime('%d/%m %Hh%M %Z')}")
    maj_html = (
        '<p style="margin:0 0 6px 0;font-size:11px;color:#888;">' + " · ".join(maj_parts) + "</p>"
        if maj_parts
        else ""
    )

    # Partie 48 h omise (webservice MF injoignable au dernier essai) : ``ind`` à
    # ``None`` → on ne rend NI l'en-tête de section, NI la fraîcheur, NI la grille.
    # On n'invente pas de repli (l'ancien repli ARPEGE couvrait 4 j, pas 48 h, et
    # doublonnait la tendance 10 j). L'omission est expliquée au rapport de bug.
    # Sinon, en-tête de la prévision officielle MF.
    if ind is None:
        section_mf = ""
        maj_html = ""
    else:
        # Portail-api (ADR-0021) : c'est le **modèle AROME** au point, picto **dérivé**
        # — pas la prévi officielle post-traitée. Étiquette honnête (le détail fin reste
        # l'affaire du site officiel MF).
        section_mf = (
            '<h2 style="margin:18px 0 8px 0;font-size:17px;color:#2c3e50;'
            'border-bottom:2px solid #eee;padding-bottom:4px;">'
            "Prévision Météo-France — modèle AROME (picto dérivé)</h2>"
        )

    return f"""<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta charset="utf-8">
<title>Météo</title>
</head><body style="margin:0;padding:0;background:#f4f4f4;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:16px;background:white;">
  <h2 style="margin:0 0 12px 0;font-size:20px;color:#2c3e50;">{titre_h2}{
        f'<span style="font-weight:400;color:#888;font-size:15px;"> — {lieu}</span>' if lieu else ""
    }</h2>
  {section_mf}
  {maj_html}
  {bloc_vigilance}
  {bloc_restrictions}
  {bloc_grille}
  {bloc_guides_tendance}
  {bloc_carte}
  {bloc_sources_semaine}
  {bloc_rapport_bug(anomalies or [], now_utc_ts)}
</div>
</body></html>"""


def composer_email(
    ind: IndicateursVeille | None,
    alertes: list[Alerte],
    config: dict[str, Any],
    maintenant: datetime,
    chart_48h_base64: str = "",
    cartes_grille: CartesGrille | None = None,
    vigilance: VigilanceDepartementDP | None = None,
    prevision_horaire: pd.DataFrame | None = None,
    updated_on: pd.Timestamp | None = None,
    position: dict[str, Any] | None = None,
    bloc_guides_tendance: str = "",
    bloc_sources_semaine: str = "",
    cartes_longue: Any = None,
    bloc_semaine_texte: str = "",
    anomalies: list[Anomalie] | None = None,
    uv_journalier: UVJournalier | None = None,
    restrictions_eau: RestrictionsEau | None = None,
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
    # ADR-0014 : tout en heure locale ; source = prévision officielle MF (la
    # fraîcheur ``updated_on`` est portée par le titre, pas le footer).
    tz_locale = config.get("site", {}).get("tz", "Europe/Paris")
    # Commune = point de grille MF réellement renvoyé (« Sains »…), spécifique à
    # la section MF. Lieu = localisation générale du site (config), portée par le
    # titre principal car valable pour tout le mail (48 h + semaine).
    commune = (position or {}).get("name")
    lieu = config.get("site", {}).get("lieu")
    adresse_site = config.get("site", {}).get("adresse", "")
    now_utc_ts = pd.Timestamp(maintenant)
    now_utc_ts = (
        now_utc_ts.tz_localize("UTC") if now_utc_ts.tzinfo is None else now_utc_ts.tz_convert("UTC")
    )
    # Moment d'envoi (matin / après-midi) = heure locale (cron 6h30/18h30, D4).
    moment = moment_envoi(now_utc_ts, tz_locale)
    sujet = composer_sujet(
        alertes,
        maintenant,
        email_cfg["sujet_template"],
        moment=moment,
        tz_locale=tz_locale,
        vigilance=vigilance,
    )
    texte = composer_texte(
        ind,
        alertes,
        maintenant,
        moment=moment,
        tz_locale=tz_locale,
        prevision_horaire=prevision_horaire,
        updated_on=updated_on,
        bloc_semaine_texte=bloc_semaine_texte,
    )
    alertes_config = config.get("alertes", {})
    html = composer_html(
        ind,
        alertes,
        maintenant,
        commune=commune,
        chart_48h_base64=chart_48h_base64,
        cartes_grille=cartes_grille,
        vigilance=vigilance,
        prevision_horaire=prevision_horaire,
        seuils_config=alertes_config,
        moment=moment,
        tz_locale=tz_locale,
        updated_on=updated_on,
        bloc_guides_tendance=bloc_guides_tendance,
        bloc_sources_semaine=bloc_sources_semaine,
        cartes_longue=cartes_longue,
        lieu=lieu,
        anomalies=anomalies,
        uv_journalier=uv_journalier,
        restrictions_eau=restrictions_eau,
        adresse_site=adresse_site,
    )
    return EmailComposed(sujet=sujet, texte=texte, html=html)


def composer_email_echec(
    config: dict[str, Any],
    maintenant: datetime,
    etape: str,
    exc: BaseException,
    traceback_str: str = "",
) -> EmailComposed:
    """Mail d'échec dur : le mail météo n'a pas pu être composé.

    On envoie quand même un mail (en plus de l'alerte GitHub Actions) avec le
    **maximum d'infos de debug** — étape, type/message d'exception, contexte
    (instant, site) et trace — pour accélérer le diagnostic.
    """
    site = config.get("site", {})
    now = pd.Timestamp(maintenant)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    tz_locale = site.get("tz", "Europe/Paris")
    now_loc = now.tz_convert(tz_locale)

    contexte = [
        ("Étape", etape),
        ("Erreur", f"{type(exc).__name__}: {exc}"),
        ("Quand", f"{now:%Y-%m-%d %H:%M} UTC ({now_loc:%d/%m %Hh%M %Z})"),
        ("Site", f"lat={site.get('latitude')} lon={site.get('longitude')} {site.get('lieu', '')}"),
    ]
    sujet = f"⚠ Veille météo — ÉCHEC ({etape})"
    texte = (
        "VEILLE MÉTÉO — ÉCHEC D'ENVOI\n"
        + "=" * 70
        + "\n"
        + "\n".join(f"{k} : {v}" for k, v in contexte)
        + ("\n\nTrace :\n" + traceback_str if traceback_str else "")
        + "\n\n(Le mail météo normal n'a pas pu être composé. "
        "Ce message contient les infos de debug.)"
    )
    ctx_html = "".join(
        f'<li style="margin:3px 0;"><strong>{escape(k)}</strong> : {escape(v)}</li>'
        for k, v in contexte
    )
    trace_html = (
        '<pre style="margin:10px 0 0 0;padding:8px;background:#f6f6f6;border-radius:4px;'
        'font-size:11px;color:#444;white-space:pre-wrap;word-break:break-word;overflow-x:auto;">'
        + escape(traceback_str)
        + "</pre>"
        if traceback_str
        else ""
    )
    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>'
        '<body style="margin:0;padding:0;background:#f4f4f4;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;\">"
        '<div style="max-width:600px;margin:0 auto;padding:16px;background:white;">'
        '<h2 style="margin:0 0 12px 0;font-size:20px;color:#a00000;">'
        "⚠ Veille météo — échec d'envoi</h2>"
        '<p style="font-size:13px;color:#555;">Le mail météo normal n\'a pas pu être '
        "composé. Détails pour debug :</p>"
        f'<ul style="font-size:13px;color:#444;line-height:1.5;">{ctx_html}</ul>'
        f"{trace_html}"
        "</div></body></html>"
    )
    return EmailComposed(sujet=sujet, texte=texte, html=html)
