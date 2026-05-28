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

from .alertes import Alerte, resume_alertes
from .indicateurs import IndicateursVeille


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
METHODE_ETP = "FAO 56 Penman-Monteith horaire (socle, cf. ADR-0004)"
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
) -> str:
    """Corps email texte simple — fallback universel et lisible mobile."""
    lignes: list[str] = []
    lignes.append(f"Veille météo — {maintenant.strftime('%A %d %B %Y, %H:%M %Z')}")
    lignes.append("=" * 60)
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

    def fmt(label: str, val: str, win: str) -> str:
        return f"  {label:<22}: {val:>10}   [{win}]"

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
    lignes.append(fmt("ETP du jour", f"{ind.etp_jour_mm:.1f} mm", "0-24 h, FAO socle"))
    lignes.append(fmt("Bilan P-ETP 7 j", f"{ind.bilan_eau_7j_mm:.1f} mm", "0-7 j"))
    flag = "OUI" if ind.tension_irrigation else "non"
    lignes.append(fmt("Tension irrigation", flag, "heuristique config"))
    lignes.append("")
    lignes.append("-" * 60)
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

    table_ind = (
        '<table style="width:100%;border-collapse:collapse;font-size:15px;">'
        + row("T° min nuit", f"{ind.temperature_min_24h_celsius:.1f} °C", "0-24 h")
        + row("T° max jour", f"{ind.temperature_max_24h_celsius:.1f} °C", "0-24 h")
        + row("Pluie cumulée", f"{ind.cumul_pluie_24h_mm:.1f} mm", "0-24 h")
        + row("Proba. pluie max", f"{ind.prob_pluie_max_24h_pct:.0f} %", "proba horaire max 0-24 h")
        + row("Vent moy max", f"{ind.vent_max_24h_kmh:.0f} km/h", "0-24 h")
        + row("Rafales max", f"{ind.rafales_max_24h_kmh:.0f} km/h", "0-24 h")
        + row("ETP du jour", f"{ind.etp_jour_mm:.1f} mm", "0-24 h · FAO P-M socle")
        + "</table>"
    )

    flag = "OUI" if ind.tension_irrigation else "non"
    table_bilan = (
        '<table style="width:100%;border-collapse:collapse;font-size:15px;">'
        + row("Cumul pluie 48 h", f"{ind.cumul_pluie_48h_mm:.1f} mm", "0-48 h")
        + row("Cumul pluie 72 h", f"{ind.cumul_pluie_72h_mm:.1f} mm", "0-72 h")
        + row("Proba. pluie max", f"{ind.prob_pluie_max_72h_pct:.0f} %", "proba horaire max 0-72 h")
        + row("Bilan P-ETP 7 j", f"{ind.bilan_eau_7j_mm:.1f} mm", "0-7 j")
        + row("Tension irrigation", flag, "heuristique config")
        + "</table>"
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

    return f"""<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta charset="utf-8">
<title>Veille météo</title>
</head><body style="margin:0;padding:0;background:#f4f4f4;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:16px;background:white;">
  <h2 style="margin:0 0 4px 0;font-size:20px;color:#2c3e50;">Veille météo</h2>
  <p style="margin:0 0 16px 0;font-size:13px;color:#888;">
    {maintenant.strftime("%A %d %B %Y, %H:%M %Z")} — La Petite Claye, Pleine-Fougères
  </p>
  {bandeau}
  {_bloc_chart(chart_72h_base64)}
  <h3 style="margin:16px 0 8px 0;font-size:15px;color:#34495e;">Indicateurs 24 h</h3>
  {table_ind}
  <h3 style="margin:16px 0 8px 0;font-size:15px;color:#34495e;">Bilan hydrique &amp; horizon</h3>
  {table_bilan}
  {_bloc_carte_synoptique(carte_synoptique_base64)}
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
    texte = composer_texte(ind, alertes, maintenant, url_fiches=url_fiches)
    html = composer_html(
        ind,
        alertes,
        maintenant,
        url_fiches=url_fiches,
        chart_72h_base64=chart_72h_base64,
        carte_synoptique_base64=carte_synoptique_base64,
    )
    return EmailComposed(sujet=sujet, texte=texte, html=html)
