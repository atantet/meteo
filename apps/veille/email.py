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
- ``#E69F00`` orange — rafales, warnings, risque mildiou

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

from .alertes import Alerte, resume_alertes
from .indicateurs import (
    IndicateursVeille,
    degrees_to_cardinal,
    direction_dominante_vecteur,
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


# Source explicite — adapté à la config par défaut de l'App 1 Veille
# (cf. config/veille.yaml ``source_meteo.modeles``).
SOURCE_DEFAUT = "Open-Meteo · AROME France HD 1.3 km (Météo-France)"
METHODE_ETP = "FAO 56 Penman-Monteith horaire (socle)"
CRON_EXPLAIN = "17 4 * * * UTC = 05:17 Paris hiver / 06:17 Paris été"
SITE_EXPLAIN = "8 La Petite Claye, 35610 Pleine-Fougères (48.5420 N, 1.6155 W, alt 30 m)"


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
            parts.append(f"{nom_fenetre} {libelle(code)}")
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
    etp_horaire_48h: pd.Series | None = None,
    now_utc: pd.Timestamp | None = None,
    tz_locale: str = "Europe/Paris",
) -> str:
    """Grille unifiée J+0 / J+1 — pictos + T° + Pluie + Vent + HR.

    Source : 48 premières heures de la prévision (AROME France HD
    1.3 km Open-Meteo). Substitue les anciennes tables "Indicateurs
    24 h" et "Horizon pluie 48-72 h" pour une lecture en un coup d'œil.

    Layout : un mini-tableau par jour (5 lignes × 3 colonnes
    matin/midi/soir), deux tableaux empilés. Plus lisible sur mobile
    qu'un grand tableau 7 colonnes.

    ``etp_horaire_48h`` (Series indexée UTC) provient du calcul socle
    FAO Penman-Monteith — utilisée pour ETP du jour et bilan eau 48 h.
    Si ``None`` ou vide, ces cellules affichent "—".
    """
    if prevision_horaire is None:
        return ""

    from apps.shared.pictograms import code_dominant_fenetre, icone_base64, libelle

    horaire_loc = prevision_horaire.copy()
    horaire_loc.index = pd.DatetimeIndex(horaire_loc.index).tz_convert(tz_locale)

    # Fenêtre calendaire [J0 00 h 00 ; J0+48 h] en heure locale, alignée
    # sur le titre du mail. Si ``now_utc`` non fourni (rétro-compat),
    # on prend les 48 premières heures du DataFrame.
    if now_utc is not None:
        now_loc = now_utc.tz_convert(tz_locale)
        x_min = now_loc.normalize()
        x_max = x_min + pd.Timedelta(hours=48)
        horaire_48h = horaire_loc.loc[(horaire_loc.index >= x_min) & (horaire_loc.index < x_max)]
    else:
        horaire_48h = horaire_loc.head(48)
    if horaire_48h.empty:
        return ""

    # ETP horaire socle alignée sur le même fuseau pour pouvoir splitter
    # par jour local (ETP du jour J+0 vs J+1).
    if etp_horaire_48h is not None and not etp_horaire_48h.empty:
        etp_loc = etp_horaire_48h.copy()
        etp_loc.index = pd.DatetimeIndex(etp_loc.index).tz_convert(tz_locale)
    else:
        etp_loc = None

    jours_uniques = pd.DatetimeIndex(horaire_48h.index).normalize().unique()[:2]
    tableaux: list[str] = []

    for jour in jours_uniques:
        jour_loc = pd.Timestamp(jour, tz=tz_locale) if jour.tzinfo is None else jour
        jour_label = (
            JOURS_FR[jour_loc.weekday()].capitalize() + f" {jour_loc.day:02d}/{jour_loc.month:02d}"
        )

        # En-tête : titre du jour + colonnes matin/midi/soir.
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

        def cellule_picto(jour: pd.Timestamp) -> str:
            cells = []
            for _nom, h_debut, h_fin in FENETRES_VEILLE:
                masque = _masque_fenetre(horaire_48h, jour, h_debut, h_fin)
                if "weather_code" in horaire_48h.columns:
                    code = code_dominant_fenetre(horaire_48h.loc[masque, "weather_code"])
                else:
                    code = None
                if code is None:
                    cells.append('<td style="padding:1px 4px;text-align:center;">—</td>')
                else:
                    uri = icone_base64(code)
                    alt = libelle(code)
                    cells.append(
                        '<td style="padding:1px 4px;text-align:center;">'
                        f'<img src="{uri}" alt="{alt}" title="{alt}" '
                        'style="width:56px;height:56px;display:block;margin:0 auto;">'
                        "</td>"
                    )
            # Bandeau continu : fond sombre sur le <tr> entier (mieux que
            # 4 rectangles séparés). Le label "Météo" passe en gris clair
            # pour rester lisible sur fond foncé.
            return (
                '<tr style="background:#34495e;">'
                '<td style="padding:4px 8px;color:#cfd6dc;font-size:13px;">Météo</td>'
                + "".join(cells)
                + "</tr>"
            )

        def serie_fenetre(jour: pd.Timestamp, colonne: str, h_debut: int, h_fin: int) -> pd.Series:
            return _serie_fenetre(horaire_48h, jour, colonne, h_debut, h_fin)

        def ligne_indicateur(label: str, formatter, jour_courant: pd.Timestamp = jour) -> str:
            """Construit une ligne ``<tr>`` avec un libellé + 3 cellules formatées.

            ``formatter`` reçoit ``(jour, h_debut, h_fin)`` et renvoie une string.
            ``jour_courant`` est explicitement fourni pour éviter la capture de
            la variable de boucle ``jour`` (B023).
            """
            cells = []
            for _nom, h_debut, h_fin in FENETRES_VEILLE:
                val_str = formatter(jour_courant, h_debut, h_fin)
                cells.append(
                    '<td style="padding:4px;text-align:center;'
                    "font-variant-numeric:tabular-nums;font-size:13px;"
                    "font-weight:700;"
                    f'color:#34495e;">{val_str}</td>'
                )
            return (
                f'<tr><td style="padding:4px 8px;color:#555;font-size:13px;">{label}</td>'
                + "".join(cells)
                + "</tr>"
            )

        def fmt_t_min_max(jour, h_debut, h_fin) -> str:
            serie_k = serie_fenetre(jour, "temperature_2m", h_debut, h_fin)
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

        def fmt_pluie(jour, h_debut, h_fin) -> str:
            serie = serie_fenetre(jour, "precipitation", h_debut, h_fin)
            if serie.empty:
                return "—"
            mm = serie.sum()
            proba = serie_fenetre(jour, "probabilite_pluie_pct", h_debut, h_fin)
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

        def fmt_vent(jour, h_debut, h_fin) -> str:
            vent = serie_fenetre(jour, "vitesse_vent_10m", h_debut, h_fin)
            rafales = serie_fenetre(jour, "rafales_vent_10m", h_debut, h_fin)
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

        def fmt_hr(jour, h_debut, h_fin) -> str:
            serie = serie_fenetre(jour, "humidite_relative", h_debut, h_fin)
            if serie.empty:
                return "—"
            return f"{serie.mean() * 100:.0f}{_unite('%')}"

        def fmt_vent_direction(jour, h_debut, h_fin) -> str:
            sub = horaire_48h.loc[_masque_fenetre(horaire_48h, jour, h_debut, h_fin)]
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

        # ETP du jour : agrégation 24 h depuis la série ETP horaire socle
        # (FAO Penman-Monteith). Affichée en une seule cellule centrée
        # (colspan=3) sous l'HR.
        def cellule_etp_jour(jour_courant: pd.Timestamp = jour) -> str:
            if etp_loc is None:
                val = "—"
            else:
                masque_etp = etp_loc.index.normalize() == jour_courant
                serie = etp_loc.loc[masque_etp].dropna()
                val = f"{serie.sum():.1f}{_unite('mm')}" if not serie.empty else "—"
            return (
                '<tr><td style="padding:4px 8px;color:#555;font-size:13px;">'
                "ETP du jour</td>"
                f'<td colspan="{len(FENETRES_VEILLE)}" '
                'style="padding:4px;text-align:center;'
                'font-variant-numeric:tabular-nums;font-size:13px;color:#34495e;font-weight:700;">'
                f"{val}</td></tr>"
            )

        lignes = [
            en_tete,
            cellule_picto(jour),
            ligne_indicateur("T° min/max", fmt_t_min_max),
            ligne_indicateur("Pluie / proba max", fmt_pluie),
            ligne_indicateur("Vent moy / rafales", fmt_vent),
            ligne_indicateur("Vent direction", fmt_vent_direction),
            ligne_indicateur("HR moyenne", fmt_hr),
            cellule_etp_jour(),
        ]

        tableaux.append(
            '<table style="width:100%;border-collapse:collapse;'
            'margin:8px 0;border:1px solid #eee;border-radius:4px;">' + "".join(lignes) + "</table>"
        )
    # Bilan eau 48 h = pluie cumul 48h - ETP cumul 48h (ETP socle FAO).
    pluie_48h = (
        horaire_48h["precipitation"].sum() if "precipitation" in horaire_48h.columns else 0.0
    )
    etp_48h = float(etp_loc.sum()) if etp_loc is not None else 0.0
    bilan_48h = pluie_48h - etp_48h
    couleur_bilan = "#009E73" if bilan_48h >= 0 else "#D55E00"
    bilan_html = (
        '<table style="width:100%;border-collapse:collapse;margin:6px 0 0 0;'
        'font-size:13px;">'
        '<tr><td style="padding:6px 8px;color:#555;">Bilan eau 48 h (P − ETP)</td>'
        f'<td style="padding:6px 8px;text-align:right;font-weight:700;'
        f'color:{couleur_bilan};font-variant-numeric:tabular-nums;">'
        f"{bilan_48h:+.1f}{_unite('mm')}</td></tr>"
        '<tr><td colspan="2" style="padding:0 8px 6px 8px;'
        'color:#aaa;font-size:11px;text-align:right;">'
        f"P = {pluie_48h:.1f}{_unite('mm')} · ETP = {etp_48h:.1f}{_unite('mm')}</td></tr>"
        "</table>"
    )

    return (
        '<h3 style="margin:14px 0 6px 0;font-size:15px;color:#34495e;">'
        "Tendance 48 h (AROME France HD 1.3 km)</h3>" + "".join(tableaux) + bilan_html
    )


def _bloc_pictogrammes_veille(
    prevision_horaire: pd.DataFrame | None,
    tz_locale: str = "Europe/Paris",
) -> str:
    """[DEPRECATED] Ancienne bande pictos seule.

    Remplacée par ``_bloc_grille_indicateurs_48h`` qui regroupe pictos
    + indicateurs en une grille unifiée. Conservée pour rétrocompat
    de l'API publique tant qu'un consommateur la référence.
    """
    if prevision_horaire is None or "weather_code" not in prevision_horaire.columns:
        return ""

    from apps.shared.pictograms import code_dominant_fenetre, icone_base64, libelle

    horaire_loc = prevision_horaire.copy()
    horaire_loc.index = pd.DatetimeIndex(horaire_loc.index).tz_convert(tz_locale)
    horaire_48h = horaire_loc.head(48)
    if horaire_48h.empty:
        return ""

    # Identifie les 2 jours locaux couverts par les 48 h.
    jours_uniques = pd.DatetimeIndex(horaire_48h.index).normalize().unique()[:2]
    fenetres = (
        ("Matin", 6, 12),
        ("Midi", 12, 16),
        ("Soir", 16, 21),
    )

    cellules = []
    for jour in jours_uniques:
        jour_loc = pd.Timestamp(jour, tz=tz_locale) if jour.tzinfo is None else jour
        jour_label = JOURS_FR[jour_loc.weekday()][:3] + f" {jour_loc.day:02d}/{jour_loc.month:02d}"
        rangee_cellules = [
            f'<td style="padding:4px 8px;font-size:12px;color:#888;white-space:nowrap;">'
            f"{jour_label}</td>"
        ]
        for nom_fenetre, h_debut, h_fin in fenetres:
            masque = (horaire_48h.index.normalize() == jour) & (
                (horaire_48h.index.hour >= h_debut) & (horaire_48h.index.hour < h_fin)
            )
            codes_fenetre = horaire_48h.loc[masque, "weather_code"]
            code = code_dominant_fenetre(codes_fenetre)
            icone_uri = icone_base64(code)
            alt = libelle(code)
            rangee_cellules.append(
                f'<td style="padding:4px;text-align:center;">'
                f'<img src="{icone_uri}" alt="{alt}" title="{alt}" '
                f'style="width:48px;height:48px;display:block;margin:0 auto;">'
                f'<div style="font-size:10px;color:#888;margin-top:2px;">{nom_fenetre}</div>'
                f"</td>"
            )
        cellules.append("<tr>" + "".join(rangee_cellules) + "</tr>")

    en_tete_fenetres = (
        '<tr style="font-size:11px;color:#aaa;">'
        "<td></td>"
        + "".join(
            f'<td style="text-align:center;padding:2px;">{nom}</td>' for nom, _, _ in fenetres
        )
        + "</tr>"
    )

    return (
        '<h3 style="margin:14px 0 6px 0;font-size:14px;color:#34495e;">'
        "Tendance 48 h (AROME France HD 1.3 km)</h3>"
        '<table style="width:100%;border-collapse:collapse;'
        'background:#fafafa;border-radius:4px;">'
        + en_tete_fenetres
        + "".join(cellules)
        + "</table>"
    )


def _bloc_risque_maladies(
    prevision_horaire: pd.DataFrame | None,
    config: dict[str, Any],
    now_utc: pd.Timestamp | None = None,
    tz_locale: str = "Europe/Paris",
) -> str:
    """Bloc HTML "Risque maladies" — homogène en format avec la grille Tendance.

    Pour chaque jour affiché (J0, J+1) : un mini-tableau avec colonnes
    Nuit / Matin / Après-midi / Soir et 2 lignes (T° min, h HR ≥ seuil).
    Un bandeau coloré par jour synthétise la condition globale 24 h
    (T_min ≥ seuil_T ET ≥ heures_min HR au-dessus du seuil HR).

    Sémantique : constat météo générique (oïdium, botrytis, alternaria,
    mildiou…) pour orienter la décision d'aération nocturne, **pas** un
    modèle pathogène. Smith mildiou tomate spécifique reste calculé en
    arrière-plan dans IndicateursVeille pour cross-check ultérieur.

    Vide si ``risque_maladies`` désactivé dans config ou si la prévision
    n'a pas les colonnes nécessaires (humidité relative, température).
    """
    rm_cfg = config.get("alertes", {}).get("risque_maladies", {})
    if not rm_cfg.get("actif", False) or prevision_horaire is None:
        return ""

    t_min_seuil = float(rm_cfg.get("t_min_nuit_celsius", 15.0))
    hr_seuil = float(rm_cfg.get("hr_seuil", 0.90))
    heures_min_24h = int(rm_cfg.get("heures_min", 6))

    horaire_loc = prevision_horaire.copy()
    horaire_loc.index = pd.DatetimeIndex(horaire_loc.index).tz_convert(tz_locale)
    # Fenêtre calendaire [J0 00 h 00 ; J0+48 h] alignée sur la grille
    # Tendance et le titre du mail.
    if now_utc is not None:
        now_loc = now_utc.tz_convert(tz_locale)
        x_min = now_loc.normalize()
        x_max = x_min + pd.Timedelta(hours=48)
        horaire_48h = horaire_loc.loc[(horaire_loc.index >= x_min) & (horaire_loc.index < x_max)]
    else:
        horaire_48h = horaire_loc.head(48)
    if (
        horaire_48h.empty
        or "temperature_2m" not in horaire_48h.columns
        or "humidite_relative" not in horaire_48h.columns
    ):
        return ""

    jours_uniques = pd.DatetimeIndex(horaire_48h.index).normalize().unique()[:2]
    tableaux_html: list[str] = []

    for jour in jours_uniques:
        jour_loc = pd.Timestamp(jour, tz=tz_locale) if jour.tzinfo is None else jour
        jour_label = (
            JOURS_FR[jour_loc.weekday()].capitalize() + f" {jour_loc.day:02d}/{jour_loc.month:02d}"
        )

        # Agrégation 24 h pour le bandeau du jour : utilise les mêmes
        # règles que l'alerte ``risque_maladies`` (cf. alertes.py).
        masque_jour = horaire_48h.index.normalize() == jour
        t_jour = horaire_48h.loc[masque_jour, "temperature_2m"].dropna() - 273.15
        hr_jour = horaire_48h.loc[masque_jour, "humidite_relative"].dropna()
        if t_jour.empty or hr_jour.empty:
            t_min_24h: float | None = None
            h_hum_24h = 0
            condition_propice = False
        else:
            t_min_24h = float(t_jour.min())
            h_hum_24h = int((hr_jour >= hr_seuil).sum())
            condition_propice = t_min_24h >= t_min_seuil and h_hum_24h >= heures_min_24h
        couleur = "#E69F00" if condition_propice else "#009E73"
        if t_min_24h is None:
            bandeau_titre = f"{jour_label} — données insuffisantes pour le jour entier"
        elif condition_propice:
            bandeau_titre = (
                f"{jour_label} — conditions propices : "
                f"T° min {t_min_24h:.1f} °C, "
                f"{h_hum_24h} h HR ≥ {hr_seuil * 100:.0f} %"
            )
        else:
            bandeau_titre = (
                f"{jour_label} — pas de signal marqué : "
                f"T° min {t_min_24h:.1f} °C, "
                f"{h_hum_24h} h HR ≥ {hr_seuil * 100:.0f} %"
            )

        # En-tête de mini-tableau aligné sur la grille Tendance.
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

        def _cellule_valeur(html_val: str) -> str:
            return (
                '<td style="padding:4px;text-align:center;'
                "font-variant-numeric:tabular-nums;font-size:13px;"
                'font-weight:700;color:#34495e;">'
                f"{html_val}</td>"
            )

        # T° min par fenêtre
        cells_tmin: list[str] = []
        for _nom, h_debut, h_fin in FENETRES_VEILLE:
            serie_k = _serie_fenetre(horaire_48h, jour, "temperature_2m", h_debut, h_fin)
            if serie_k.empty:
                cells_tmin.append(_cellule_valeur("—"))
            else:
                t_min = serie_k.min() - 273.15
                cells_tmin.append(
                    _cellule_valeur(
                        f'<span style="color:#0072B2;">{t_min:.0f}</span>{_unite("°C")}'
                    )
                )
        ligne_tmin = (
            '<tr><td style="padding:4px 8px;color:#888;font-size:11px;">T° min</td>'
            + "".join(cells_tmin)
            + "</tr>"
        )

        # h HR ≥ seuil par fenêtre
        cells_hr: list[str] = []
        for _nom, h_debut, h_fin in FENETRES_VEILLE:
            serie = _serie_fenetre(horaire_48h, jour, "humidite_relative", h_debut, h_fin)
            if serie.empty:
                cells_hr.append(_cellule_valeur("—"))
            else:
                n_h = int((serie >= hr_seuil).sum())
                # Mise en évidence si la fenêtre est majoritairement
                # humectée (≥ 3 h sur 6 h = moitié).
                if n_h >= 3:
                    valeur = f'<span style="color:#E69F00;">{n_h}</span>{_unite("h")}'
                else:
                    valeur = f"{n_h}{_unite('h')}"
                cells_hr.append(_cellule_valeur(valeur))
        ligne_hr = (
            f'<tr><td style="padding:4px 8px;color:#888;font-size:11px;">'
            f"h HR ≥ {hr_seuil * 100:.0f} %</td>" + "".join(cells_hr) + "</tr>"
        )

        tableau_jour = (
            f'<div style="margin:6px 0 8px 0;padding:6px 10px;background:{couleur};'
            f'color:white;border-radius:4px;font-size:13px;">{bandeau_titre}</div>'
            '<table style="width:100%;border-collapse:collapse;'
            'margin:8px 0;border:1px solid #eee;border-radius:4px;">'
            + en_tete
            + ligne_tmin
            + ligne_hr
            + "</table>"
        )
        tableaux_html.append(tableau_jour)

    return (
        '<h3 style="margin:14px 0 6px 0;font-size:15px;color:#34495e;">'
        "Risque maladies — conditions d'aération</h3>"
        + "".join(tableaux_html)
        + '<p style="margin:6px 0;font-size:12px;color:#888;font-style:italic;">'
        f"Constat météo informationnel : T° min ≥ {t_min_seuil:.0f} °C "
        f"ET ≥ {heures_min_24h} h HR ≥ {hr_seuil * 100:.0f} % sur 24 h "
        "= conditions propices au développement de maladies (oïdium, botrytis, "
        "alternaria, mildiou…) sous abri mal aéré la nuit. Pas un modèle "
        "pathogène — décision d'aération vous revient."
        "</p>"
    )


def composer_sujet(alertes: list[Alerte], maintenant: datetime, template: str) -> str:
    """Formate le sujet selon template config.

    Variables disponibles : ``{date}`` (YYYY-MM-DD), ``{alertes_resume}``
    (ex. "gel + vent fort" ou "RAS"), ``{alertes_count}``.
    """
    return template.format(
        date=maintenant.strftime("%Y-%m-%d"),
        alertes_resume=resume_alertes(alertes),
        alertes_count=len(alertes),
    )


def composer_texte(
    ind: IndicateursVeille,
    alertes: list[Alerte],
    maintenant: datetime,
    url_fiches: str = "",
    source: str = SOURCE_DEFAUT,
    methode_etp: str = METHODE_ETP,
    cron: str = CRON_EXPLAIN,
    site: str = SITE_EXPLAIN,
    tz_locale: str = "Europe/Paris",
    prevision_horaire: pd.DataFrame | None = None,
) -> str:
    """Corps email texte simple — fallback universel et lisible mobile."""
    lignes: list[str] = []
    lignes.append(f"Veille météo — {format_date_fr(maintenant)}")
    lignes.append("=" * 70)
    if ind.prevision_t0_utc is not None:
        t0_loc = ind.prevision_t0_utc
        if t0_loc.tzinfo is None:
            t0_loc = t0_loc.tz_localize("UTC")
        t0_loc = t0_loc.tz_convert(tz_locale)
        debut_fenetre = t0_loc.normalize()
        fenetre_label = f"{debut_fenetre.strftime('%d/%m/%Y')} 00h00 - 48h00"
    else:
        fenetre_label = "—"
    lignes.append(f"Prévision du {fenetre_label}")
    lignes.append("")

    if alertes:
        lignes.append("ALERTES :")
        for a in alertes:
            lignes.append(f"  [{a.niveau.upper()}] {a.titre}")
            lignes.append(f"      seuil configuré : {a.seuil} {a.unite}")
        lignes.append("")
    else:
        lignes.append("Aucune alerte seuil franchi sur les prochaines 24 h.")
        lignes.append("")

    # Tendance 48 h en mots (équivalent texte de la bande pictos HTML).
    tendance_lignes = _tendance_texte_48h(prevision_horaire, tz_locale)
    if tendance_lignes:
        lignes.append("TENDANCE 48 h (AROME France HD) :")
        lignes.extend(tendance_lignes)
        lignes.append("")

    def fmt(label: str, val: str, win: str) -> str:
        return f"  {label:<22}: {val:>12}   [{win}]"

    direction = ind.direction_vent_dominante_cardinal or "—"

    lignes.append("INDICATEURS :")
    lignes.append(fmt("T° min nuit", f"{ind.temperature_min_24h_celsius:.1f} °C", "0-24 h"))
    lignes.append(fmt("T° max jour", f"{ind.temperature_max_24h_celsius:.1f} °C", "0-24 h"))
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
    lignes.append(fmt("ETP du jour", f"{ind.etp_jour_mm:.1f} mm", "0-24 h, FAO socle"))
    lignes.append("")
    lignes.append("-" * 70)
    lignes.append("Ce mail est un signal informationnel — vous gardez la décision")
    lignes.append("(cf. principe #1 du projet).")
    lignes.append("")
    lignes.append(f"Source : {source}")
    lignes.append(f"ETP    : {methode_etp}")
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
    methode_etp: str = METHODE_ETP,
    cron: str = CRON_EXPLAIN,
    site: str = SITE_EXPLAIN,
    chart_48h_base64: str = "",
    carte_synoptique_base64: str = "",
    carte_synoptique_last_modified: datetime | None = None,
    prevision_horaire: pd.DataFrame | None = None,
    risque_maladies_config: dict[str, Any] | None = None,
    tz_locale: str = "Europe/Paris",
) -> str:
    """Corps email HTML mobile-first (table inline, pas de framework)."""
    couleur_niveau = {"critique": "#D55E00", "warning": "#E69F00"}

    bandeau = ""
    if alertes:
        bandeau_items = []
        for a in alertes:
            c = couleur_niveau.get(a.niveau, "#7f8c8d")
            bandeau_items.append(
                f'<div style="margin:6px 0;padding:8px 12px;background:{c};'
                f'color:white;border-radius:4px;">'
                f"<strong>{a.titre}</strong>"
                f'<div style="font-size:0.85em;opacity:0.9;">'
                f"seuil configuré : {a.seuil} {a.unite}</div>"
                f"</div>"
            )
        bandeau = "".join(bandeau_items)
    else:
        bandeau = (
            '<div style="margin:6px 0;padding:8px 12px;background:#009E73;'
            'color:white;border-radius:4px;">'
            "Aucune alerte seuil franchi sur les prochaines 24 h."
            "</div>"
        )

    def row(label: str, valeur: str, fenetre: str) -> str:
        return (
            "<tr>"
            f'<td style="padding:4px 8px;color:#555;">{label}'
            f'<span style="font-size:0.75em;color:#aaa;margin-left:6px;">[{fenetre}]</span>'
            "</td>"
            f'<td style="padding:4px 8px;text-align:right;'
            f'font-variant-numeric:tabular-nums;font-weight:600;">{valeur}</td>'
            "</tr>"
        )

    # ``now_utc`` pour aligner la fenêtre J0 00 h 00 → J0+48 h entre
    # les blocs Tendance, Risque maladies et le graphique. On le dérive
    # de ``maintenant`` (qui peut être naïf ; on suppose UTC).
    now_utc_ts = pd.Timestamp(maintenant)
    if now_utc_ts.tzinfo is None:
        now_utc_ts = now_utc_ts.tz_localize("UTC")
    else:
        now_utc_ts = now_utc_ts.tz_convert("UTC")

    # Bloc "Risque maladies" générique (remplace l'ancien Smith
    # spécifique tomate). Wrap config en dict pour le helper.
    config_pour_bloc = {"alertes": {"risque_maladies": risque_maladies_config or {}}}
    bloc_risque_maladies = _bloc_risque_maladies(
        prevision_horaire, config_pour_bloc, now_utc=now_utc_ts, tz_locale=tz_locale
    )
    bloc_grille = _bloc_grille_indicateurs_48h(
        prevision_horaire,
        etp_horaire_48h=ind.etp_horaire_48h,
        now_utc=now_utc_ts,
        tz_locale=tz_locale,
    )
    bloc_carte = _bloc_carte_synoptique(
        carte_synoptique_base64,
        last_modified=carte_synoptique_last_modified,
        tz_locale=tz_locale,
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
        f'<div><strong style="color:#555;">ETP</strong> : {methode_etp}</div>'
        f'<div><strong style="color:#555;">Cron</strong> : {cron}</div>'
        f'<div><strong style="color:#555;">Site</strong> : {site}</div>'
        f"{lien_fiches}"
        "</div>"
    )

    # Fenêtre de prévision : du J0 00 h 00 locale + 48 h. Date présentée
    # dans un format monospace + fond clair pour la rendre légèrement
    # distinctive (police technique, vs corps du titre courant).
    if ind.prevision_t0_utc is not None:
        t0_loc = ind.prevision_t0_utc
        if t0_loc.tzinfo is None:
            t0_loc = t0_loc.tz_localize("UTC")
        t0_loc = t0_loc.tz_convert(tz_locale)
        debut_fenetre = t0_loc.normalize()
        date_html = (
            '<span style="font-family:Menlo,Consolas,monospace;font-size:0.88em;'
            'background:#f4f4f4;padding:1px 6px;border-radius:3px;color:#34495e;">'
            f"{debut_fenetre.strftime('%d/%m/%Y')} 00h00 - 48h00"
            "</span>"
        )
    else:
        date_html = "—"

    return f"""<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta charset="utf-8">
<title>Veille météo</title>
</head><body style="margin:0;padding:0;background:#f4f4f4;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:16px;background:white;">
  <h2 style="margin:0 0 4px 0;font-size:20px;color:#2c3e50;">
    Prévision du {date_html}
  </h2>
  <p style="margin:0 0 12px 0;font-size:13px;color:#888;">
    La Petite Claye, Pleine-Fougères
  </p>
  {bandeau}
  {bloc_grille}
  {bloc_risque_maladies}
  {bloc_carte}
  <h3 style="margin:16px 0 6px 0;font-size:13px;color:#888;">Détail horaire 48 h
  <span style="font-weight:normal;font-size:12px;">(information secondaire)</span></h3>
  {_bloc_chart(chart_48h_base64)}
  <p style="margin:16px 0 0 0;font-size:12px;color:#888;font-style:italic;">
    Ce mail est un signal informationnel — vous gardez la décision.
    Les seuils sont des défauts opérationnels, ajustables dans la config.
  </p>
  {footer}
</div>
</body></html>"""


def composer_email(
    ind: IndicateursVeille,
    alertes: list[Alerte],
    config: dict[str, Any],
    maintenant: datetime,
    chart_48h_base64: str = "",
    carte_synoptique_base64: str = "",
    carte_synoptique_last_modified: datetime | None = None,
    prevision_horaire: pd.DataFrame | None = None,
) -> EmailComposed:
    """Compose sujet + texte + HTML à partir des indicateurs et de la config.

    ``chart_48h_base64`` (optionnel) sera embarqué dans le HTML comme image
    inline. ``carte_synoptique_base64`` (optionnel) sera embarquée comme
    illustration de la situation synoptique productive. Si vides, aucune
    image n'est rendue.
    """
    email_cfg = config["email"]
    url_fiches = email_cfg.get("url_fiches_indices", "") or ""
    sujet = composer_sujet(alertes, maintenant, email_cfg["sujet_template"])
    texte = composer_texte(
        ind,
        alertes,
        maintenant,
        url_fiches=url_fiches,
        prevision_horaire=prevision_horaire,
    )
    rm_config = config.get("alertes", {}).get("risque_maladies")
    html = composer_html(
        ind,
        alertes,
        maintenant,
        url_fiches=url_fiches,
        chart_48h_base64=chart_48h_base64,
        carte_synoptique_base64=carte_synoptique_base64,
        carte_synoptique_last_modified=carte_synoptique_last_modified,
        prevision_horaire=prevision_horaire,
        risque_maladies_config=rm_config,
    )
    return EmailComposed(sujet=sujet, texte=texte, html=html)
