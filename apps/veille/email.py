"""Composition de l'email matinal Veille (texte + HTML mobile-first).

Génère sujet, corps texte (fallback) et corps HTML responsive à partir
des indicateurs et alertes calculés.

Le ton reste informationnel (cf. principe n°1). L'utilisateur garde
son jugement empirique pour décider.
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

    lignes.append("INDICATEURS 24 h :")
    lignes.append(f"  T° min prévue   : {ind.temperature_min_24h_celsius:>6.1f} °C")
    lignes.append(f"  T° max prévue   : {ind.temperature_max_24h_celsius:>6.1f} °C")
    lignes.append(f"  Pluie cumulée   : {ind.cumul_pluie_24h_mm:>6.1f} mm")
    lignes.append(f"  Vent max        : {ind.vent_max_24h_kmh:>6.0f} km/h")
    lignes.append(f"  Rafales max     : {ind.rafales_max_24h_kmh:>6.0f} km/h")
    lignes.append(f"  ETP du jour     : {ind.etp_jour_mm:>6.1f} mm")
    lignes.append("")
    lignes.append("BILAN HYDRIQUE :")
    lignes.append(f"  Cumul pluie 48 h  : {ind.cumul_pluie_48h_mm:>6.1f} mm")
    lignes.append(f"  Cumul pluie 72 h  : {ind.cumul_pluie_72h_mm:>6.1f} mm")
    lignes.append(f"  Bilan P-ETP 7 j   : {ind.bilan_eau_7j_mm:>6.1f} mm")
    flag = "OUI" if ind.tension_irrigation else "non"
    lignes.append(f"  Tension irrigation : {flag}")
    lignes.append("")
    lignes.append("--")
    lignes.append("Ce mail est un signal informationnel — vous gardez la")
    lignes.append("décision (cf. principe #1 du projet).")
    if url_fiches:
        lignes.append(f"Détails et sources : {url_fiches}")
    return "\n".join(lignes)


def composer_html(
    ind: IndicateursVeille,
    alertes: list[Alerte],
    maintenant: datetime,
    url_fiches: str = "",
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

    def row(label: str, valeur: str) -> str:
        return (
            f'<tr><td style="padding:4px 8px;color:#555;">{label}</td>'
            f'<td style="padding:4px 8px;text-align:right;'
            f'font-variant-numeric:tabular-nums;font-weight:600;">{valeur}</td></tr>'
        )

    table_ind = (
        '<table style="width:100%;border-collapse:collapse;font-size:15px;">'
        + row("T° min prévue", f"{ind.temperature_min_24h_celsius:.1f} °C")
        + row("T° max prévue", f"{ind.temperature_max_24h_celsius:.1f} °C")
        + row("Pluie 24 h", f"{ind.cumul_pluie_24h_mm:.1f} mm")
        + row("Vent max", f"{ind.vent_max_24h_kmh:.0f} km/h")
        + row("Rafales max", f"{ind.rafales_max_24h_kmh:.0f} km/h")
        + row("ETP du jour", f"{ind.etp_jour_mm:.1f} mm")
        + "</table>"
    )

    flag = "OUI" if ind.tension_irrigation else "non"
    table_bilan = (
        '<table style="width:100%;border-collapse:collapse;font-size:15px;">'
        + row("Cumul pluie 48 h", f"{ind.cumul_pluie_48h_mm:.1f} mm")
        + row("Cumul pluie 72 h", f"{ind.cumul_pluie_72h_mm:.1f} mm")
        + row("Bilan P-ETP 7 j", f"{ind.bilan_eau_7j_mm:.1f} mm")
        + row("Tension irrigation", flag)
        + "</table>"
    )

    lien_fiches = (
        f'<p style="font-size:13px;color:#888;">'
        f'Détails et sources : <a href="{url_fiches}">{url_fiches}</a></p>'
        if url_fiches
        else ""
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
  <h3 style="margin:16px 0 8px 0;font-size:15px;color:#34495e;">Indicateurs 24 h</h3>
  {table_ind}
  <h3 style="margin:16px 0 8px 0;font-size:15px;color:#34495e;">Bilan hydrique</h3>
  {table_bilan}
  <p style="margin:16px 0 0 0;font-size:12px;color:#888;font-style:italic;">
    Ce mail est un signal informationnel — vous gardez la décision.
    Les seuils sont des défauts opérationnels, ajustables dans la config.
  </p>
  {lien_fiches}
</div>
</body></html>"""


def composer_email(
    ind: IndicateursVeille,
    alertes: list[Alerte],
    config: dict[str, Any],
    maintenant: datetime,
) -> EmailComposed:
    """Compose sujet + texte + HTML à partir des indicateurs et de la config."""
    email_cfg = config["email"]
    url_fiches = email_cfg.get("url_fiches_indices", "") or ""
    sujet = composer_sujet(alertes, maintenant, email_cfg["sujet_template"])
    texte = composer_texte(ind, alertes, maintenant, url_fiches=url_fiches)
    html = composer_html(ind, alertes, maintenant, url_fiches=url_fiches)
    return EmailComposed(sujet=sujet, texte=texte, html=html)
