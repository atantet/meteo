"""Composition de l'email matinal Veille (texte + HTML mobile-first).

Génère sujet, corps texte (fallback) et corps HTML responsive à partir
des indicateurs et alertes calculés.

Le ton reste informationnel (cf. principe n°1). L'utilisateur garde
son jugement empirique pour décider.

Chaque indicateur est annoté de sa **fenêtre temporelle** (entre
crochets, gris discret) et le footer du mail rappelle la **source des
données** + la **méthode de calcul ETP** + la programmation du cron
(principe n°5 transparence).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
SOURCE_DEFAUT = (
    "Open-Meteo best_match (AROME France HD 0-2 j · ICON-EU/ARPEGE 2-4 j · ECMWF IFS 4-7 j)"
)
METHODE_ETP = "FAO 56 Penman-Monteith horaire (socle)"
CRON_EXPLAIN = "30 6 * * * UTC = 07:30 Paris hiver / 08:30 Paris été"
SITE_EXPLAIN = "8 La Petite Claye, 35610 Pleine-Fougères (48.5420 N, 1.6155 W, alt 30 m)"


def _bloc_chart(chart_base64: str) -> str:
    """Bloc HTML pour le graphique 72 h embarqué (vide si non fourni)."""
    if not chart_base64:
        return ""
    return (
        '<div style="margin:12px 0;text-align:center;">'
        f'<img src="{chart_base64}" alt="Prévision 72 h" '
        'style="max-width:100%;height:auto;border-radius:4px;">'
        "</div>"
    )


def _bloc_carte_synoptique(carte_base64: str) -> str:
    """Bloc HTML pour la carte synoptique DWD (vide si non fournie)."""
    if not carte_base64:
        return ""
    return (
        '<div style="margin:18px 0 6px 0;">'
        '<h3 style="margin:0 0 6px 0;font-size:15px;color:#34495e;">'
        "Situation synoptique</h3>"
        '<div style="text-align:center;">'
        f'<img src="{carte_base64}" alt="Analyse de surface DWD" '
        'style="max-width:100%;height:auto;border-radius:4px;border:1px solid #eee;">'
        "</div>"
        '<p style="margin:4px 0 0 0;font-size:11px;color:#888;text-align:center;">'
        "Analyse de surface — Deutscher Wetterdienst (mise à jour 4×/jour)"
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
FENETRES_VEILLE = (
    ("Matin", 6, 12),
    ("Midi", 12, 16),
    ("Soir", 16, 21),
)


def _bloc_grille_indicateurs_48h(
    prevision_horaire: pd.DataFrame | None,
    tz_locale: str = "Europe/Paris",
) -> str:
    """Grille unifiée J+0 / J+1 — pictos + T° + Pluie + Vent + HR.

    Source : 48 premières heures de la prévision (= AROME France HD
    via best_match Open-Meteo). Substitue les anciennes tables
    "Indicateurs 24 h" et "Horizon pluie 48-72 h" pour une lecture
    en un coup d'œil.

    Layout : un mini-tableau par jour (5 lignes × 3 colonnes
    matin/midi/soir), deux tableaux empilés. Plus lisible sur mobile
    qu'un grand tableau 7 colonnes.
    """
    if prevision_horaire is None:
        return ""

    from apps.shared.pictograms import code_dominant_fenetre, icone_base64, libelle

    horaire_loc = prevision_horaire.copy()
    horaire_loc.index = pd.DatetimeIndex(horaire_loc.index).tz_convert(tz_locale)
    horaire_48h = horaire_loc.head(48)
    if horaire_48h.empty:
        return ""

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
                masque = (horaire_48h.index.normalize() == jour) & (
                    (horaire_48h.index.hour >= h_debut) & (horaire_48h.index.hour < h_fin)
                )
                if "weather_code" in horaire_48h.columns:
                    code = code_dominant_fenetre(horaire_48h.loc[masque, "weather_code"])
                else:
                    code = None
                if code is None:
                    cells.append('<td style="padding:4px;text-align:center;">—</td>')
                else:
                    uri = icone_base64(code)
                    alt = libelle(code)
                    cells.append(
                        '<td style="padding:4px;text-align:center;">'
                        f'<img src="{uri}" alt="{alt}" title="{alt}" '
                        'style="width:40px;height:40px;display:inline-block;">'
                        "</td>"
                    )
            return (
                '<tr><td style="padding:4px 8px;color:#888;font-size:11px;">Météo</td>'
                + "".join(cells)
                + "</tr>"
            )

        def serie_fenetre(jour: pd.Timestamp, colonne: str, h_debut: int, h_fin: int) -> pd.Series:
            masque = (horaire_48h.index.normalize() == jour) & (
                (horaire_48h.index.hour >= h_debut) & (horaire_48h.index.hour < h_fin)
            )
            if colonne not in horaire_48h.columns:
                return pd.Series([], dtype=float)
            return horaire_48h.loc[masque, colonne].dropna()

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
                    f'color:#34495e;">{val_str}</td>'
                )
            return (
                f'<tr><td style="padding:4px 8px;color:#888;font-size:11px;">{label}</td>'
                + "".join(cells)
                + "</tr>"
            )

        def fmt_t_min_max(jour, h_debut, h_fin) -> str:
            serie_k = serie_fenetre(jour, "temperature_2m", h_debut, h_fin)
            if serie_k.empty:
                return "—"
            return f"{serie_k.min() - 273.15:.0f}/{serie_k.max() - 273.15:.0f}"

        def fmt_pluie(jour, h_debut, h_fin) -> str:
            serie = serie_fenetre(jour, "precipitation", h_debut, h_fin)
            if serie.empty:
                return "—"
            mm = serie.sum()
            proba = serie_fenetre(jour, "probabilite_pluie_pct", h_debut, h_fin)
            if proba.empty:
                return f"{mm:.1f}"
            return f"{mm:.1f} ({proba.max():.0f} %)"

        def fmt_vent(jour, h_debut, h_fin) -> str:
            vent = serie_fenetre(jour, "vitesse_vent_10m", h_debut, h_fin)
            rafales = serie_fenetre(jour, "rafales_vent_10m", h_debut, h_fin)
            if vent.empty:
                return "—"
            v_moy = vent.mean() * MS_TO_KMH_VEILLE
            r_max = (rafales.max() if not rafales.empty else vent.max()) * MS_TO_KMH_VEILLE
            return f"{v_moy:.0f}/{r_max:.0f}"

        def fmt_hr(jour, h_debut, h_fin) -> str:
            serie = serie_fenetre(jour, "humidite_relative", h_debut, h_fin)
            if serie.empty:
                return "—"
            return f"{serie.mean() * 100:.0f} %"

        def fmt_vent_direction(jour, h_debut, h_fin) -> str:
            masque = (horaire_48h.index.normalize() == jour) & (
                (horaire_48h.index.hour >= h_debut) & (horaire_48h.index.hour < h_fin)
            )
            sub = horaire_48h.loc[masque]
            if sub.empty or "direction_vent_deg" not in sub.columns:
                return "—"
            deg = direction_dominante_vecteur(sub)
            if pd.isna(deg):
                return "—"
            return degrees_to_cardinal(deg)

        # ETP du jour : aggrégation 24h (somme de l'ETP horaire FAO socle
        # si dispo, sinon etp_open_meteo en mm/h). Affichée en une seule
        # cellule centrée (colspan=3) sous l'HR.
        def cellule_etp_jour(jour_courant: pd.Timestamp = jour) -> str:
            masque = horaire_48h.index.normalize() == jour_courant
            etp_col = "etp_open_meteo" if "etp_open_meteo" in horaire_48h.columns else None
            if etp_col is None:
                val = "—"
            else:
                serie = horaire_48h.loc[masque, etp_col].dropna()
                val = f"{serie.sum():.1f} mm" if not serie.empty else "—"
            return (
                '<tr><td style="padding:4px 8px;color:#888;font-size:11px;">'
                "ETP du jour</td>"
                f'<td colspan="{len(FENETRES_VEILLE)}" '
                'style="padding:4px;text-align:center;'
                'font-variant-numeric:tabular-nums;font-size:13px;color:#34495e;">'
                f"{val}</td></tr>"
            )

        lignes = [
            en_tete,
            cellule_picto(jour),
            ligne_indicateur("T° min/max (°C)", fmt_t_min_max),
            ligne_indicateur("Pluie mm (proba max)", fmt_pluie),
            ligne_indicateur("Vent moy/raf (km/h)", fmt_vent),
            ligne_indicateur("Vent direction", fmt_vent_direction),
            ligne_indicateur("HR moy", fmt_hr),
            cellule_etp_jour(),
        ]

        tableaux.append(
            '<table style="width:100%;border-collapse:collapse;'
            'margin:8px 0;border:1px solid #eee;border-radius:4px;">' + "".join(lignes) + "</table>"
        )
    # Bilan eau 48 h = pluie cumul 48h - ETP cumul 48h.
    pluie_48h = (
        horaire_48h["precipitation"].sum() if "precipitation" in horaire_48h.columns else 0.0
    )
    etp_48h = (
        horaire_48h["etp_open_meteo"].sum() if "etp_open_meteo" in horaire_48h.columns else 0.0
    )
    bilan_48h = pluie_48h - etp_48h
    couleur_bilan = "#27ae60" if bilan_48h >= 0 else "#c0392b"
    bilan_html = (
        '<table style="width:100%;border-collapse:collapse;margin:6px 0 0 0;'
        'font-size:13px;">'
        '<tr><td style="padding:6px 8px;color:#555;">Bilan eau 48 h (P − ETP)</td>'
        f'<td style="padding:6px 8px;text-align:right;font-weight:600;'
        f'color:{couleur_bilan};font-variant-numeric:tabular-nums;">'
        f"{bilan_48h:+.1f} mm</td></tr>"
        '<tr><td colspan="2" style="padding:0 8px 6px 8px;'
        'color:#aaa;font-size:11px;text-align:right;">'
        f"P = {pluie_48h:.1f} mm · ETP = {etp_48h:.1f} mm</td></tr>"
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


def _bloc_mildiou_smith(ind: IndicateursVeille) -> str:
    """Bloc HTML mildiou Smith — vide si l'indicateur n'a pas été calculé.

    Affiche le tableau journalier (T_min, h HR≥90 %, smith oui/non) sur
    la fenêtre J+1 → J+3, et un bandeau de tête vert/orange selon
    présence d'au moins une période détectée.
    """
    if ind.mildiou_smith_detail is None or ind.mildiou_smith_detail.empty:
        return ""

    detail = ind.mildiou_smith_detail
    a_risque = len(ind.mildiou_smith_jours_a_risque) > 0
    couleur = "#e67e22" if a_risque else "#27ae60"
    titre = (
        f"Mildiou tomate : période de Smith détectée sur "
        f"{len(ind.mildiou_smith_jours_a_risque)} jour(s)"
        if a_risque
        else "Mildiou tomate : pas de période de Smith détectée sur J+1 → J+3"
    )

    lignes_html = []
    for date, ligne in detail.iterrows():
        smith = "✓" if ligne["smith_period"] else "—"
        couleur_ligne = "#e67e22" if ligne["smith_period"] else "#555"
        jour_fr = JOURS_FR[date.weekday()]
        lignes_html.append(
            f"<tr>"
            f'<td style="padding:4px 8px;color:#555;">'
            f"{jour_fr} {date.day:02d}/{date.month:02d}</td>"
            f'<td style="padding:4px 8px;text-align:right;font-variant-numeric:tabular-nums;">'
            f"{ligne['t_min_celsius']:.1f} °C</td>"
            f'<td style="padding:4px 8px;text-align:right;font-variant-numeric:tabular-nums;">'
            f"{int(ligne['heures_humectation'])} h</td>"
            f'<td style="padding:4px 8px;text-align:center;color:{couleur_ligne};font-weight:600;">'
            f"{smith}</td>"
            f"</tr>"
        )

    return (
        '<h3 style="margin:16px 0 8px 0;font-size:15px;color:#34495e;">'
        "Mildiou tomate (Smith periods)</h3>"
        f'<div style="margin:6px 0 8px 0;padding:6px 10px;background:{couleur};'
        f'color:white;border-radius:4px;font-size:13px;">{titre}</div>'
        '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
        '<tr style="color:#888;font-size:12px;text-align:right;border-bottom:1px solid #eee;">'
        '<td style="padding:4px 8px;text-align:left;">Jour local</td>'
        '<td style="padding:4px 8px;">T_min</td>'
        '<td style="padding:4px 8px;">h HR ≥ 90 %</td>'
        '<td style="padding:4px 8px;text-align:center;">Smith</td>'
        "</tr>" + "".join(lignes_html) + "</table>"
        '<p style="margin:6px 0;font-size:12px;color:#888;font-style:italic;">'
        "Critère : 2 jours consécutifs T_min ≥ 10 °C ET ≥ 11 h HR ≥ 90 %. "
        "Donnée HR maille ~25 km (hors abri). Indicateur informationnel."
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
    lignes.append(f"Veille météo — {format_horodatage_fr(maintenant, tz_locale)}")
    lignes.append("=" * 70)
    t0 = format_t0_court(ind.prevision_t0_utc, tz_locale)
    lignes.append(f"Premier pas de prévision (T+0h) : {t0}")
    lignes.append("Toutes les fenêtres ci-dessous sont relatives à T+0h.")
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
    lignes.append(fmt("Cumul pluie 72 h", f"{ind.cumul_pluie_72h_mm:.1f} mm", "0-72 h"))
    lignes.append(fmt("Proba. pluie 24 h", f"{ind.prob_pluie_max_24h_pct:.0f} %", "max horaire"))
    lignes.append(fmt("Proba. pluie 72 h", f"{ind.prob_pluie_max_72h_pct:.0f} %", "max horaire"))
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
    chart_72h_base64: str = "",
    carte_synoptique_base64: str = "",
    prevision_horaire: pd.DataFrame | None = None,
    tz_locale: str = "Europe/Paris",
) -> str:
    """Corps email HTML mobile-first (table inline, pas de framework)."""
    couleur_niveau = {"critique": "#c0392b", "warning": "#e67e22"}

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
            '<div style="margin:6px 0;padding:8px 12px;background:#27ae60;'
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

    bloc_mildiou = _bloc_mildiou_smith(ind)
    bloc_grille = _bloc_grille_indicateurs_48h(prevision_horaire, tz_locale=tz_locale)

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

    horodatage = format_horodatage_fr(maintenant, tz_locale)
    t0_str = format_t0_court(ind.prevision_t0_utc, tz_locale)

    return f"""<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta charset="utf-8">
<title>Veille météo</title>
</head><body style="margin:0;padding:0;background:#f4f4f4;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:16px;background:white;">
  <h2 style="margin:0 0 4px 0;font-size:20px;color:#2c3e50;">Veille météo</h2>
  <p style="margin:0 0 4px 0;font-size:13px;color:#888;">
    {horodatage} — La Petite Claye, Pleine-Fougères
  </p>
  <p style="margin:0 0 12px 0;font-size:12px;color:#888;">
    Premier pas de prévision (T+0h) : <strong style="color:#555;">{t0_str}</strong> ·
    fenêtres ci-dessous relatives à T+0h.
  </p>
  {bandeau}
  {bloc_grille}
  {bloc_mildiou}
  {_bloc_carte_synoptique(carte_synoptique_base64)}
  <h3 style="margin:16px 0 6px 0;font-size:13px;color:#888;">Détail horaire 72 h
  <span style="font-weight:normal;font-size:12px;">(information secondaire)</span></h3>
  {_bloc_chart(chart_72h_base64)}
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
    chart_72h_base64: str = "",
    carte_synoptique_base64: str = "",
    prevision_horaire: pd.DataFrame | None = None,
) -> EmailComposed:
    """Compose sujet + texte + HTML à partir des indicateurs et de la config.

    ``chart_72h_base64`` (optionnel) sera embarqué dans le HTML comme image
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
    html = composer_html(
        ind,
        alertes,
        maintenant,
        url_fiches=url_fiches,
        chart_72h_base64=chart_72h_base64,
        carte_synoptique_base64=carte_synoptique_base64,
        prevision_horaire=prevision_horaire,
    )
    return EmailComposed(sujet=sujet, texte=texte, html=html)
