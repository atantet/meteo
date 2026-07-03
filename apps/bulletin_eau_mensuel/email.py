"""Composition de l'email du bulletin eau mensuel (texte + HTML).

Mobile-first, styles inline (compatibilité clients mail). Deux blocs
optionnels — nappe, pluie — plus un bloc prospectif (liens BSH + MF).
Ton informationnel : on **expose l'état**, on n'enjoint rien.

Réutilise ``EmailComposed`` (triplet sujet/texte/html) de la Veille pour
rester compatible avec ``apps.veille.sender``.
"""

from __future__ import annotations

import base64

import pandas as pd

from apps.shared.dates_fr import MOIS_FR
from apps.shared.style import (
    COULEUR_CHAUD,
    COULEUR_NEUTRE,
    COULEUR_PLUIE,
)
from apps.veille.email import EmailComposed

from .donnees import BulletinEau
from .graphes import graphe_nappe, graphe_pluie
from .vocabulaire import couleur_classe_nappe

# ----- Construction de blocs HTML -----


def _carte(titre: str, couleur: str, corps_html: str) -> str:
    """Bloc encadré avec barre de couleur à gauche."""
    return (
        f'<div style="border:1px solid #e6e6e6;border-left:4px solid {couleur};'
        'border-radius:6px;padding:12px 14px;margin:0 0 14px 0;">'
        f'<div style="font-size:15px;font-weight:700;color:#2c3e50;'
        f'margin-bottom:6px;">{titre}</div>'
        f'<div style="font-size:14px;color:#34495e;line-height:1.5;">{corps_html}</div>'
        "</div>"
    )


def _ligne_caveat(texte: str) -> str:
    return f'<div style="font-size:12px;color:#888;font-style:italic;margin-top:6px;">{texte}</div>'


def _bloc_nappe(b: BulletinEau) -> str:
    n = b.nappe
    if n is None:
        return ""
    couleur = couleur_classe_nappe(n.classe_saison)
    if n.delta_30j_m is None:
        couleur_tend = COULEUR_NEUTRE
        tendance = "tendance indisponible"
    elif n.delta_30j_m > 0.05:
        couleur_tend = COULEUR_PLUIE
        tendance = f"↑ +{n.delta_30j_m:.2f} m/30 j"
    elif n.delta_30j_m < -0.05:
        couleur_tend = COULEUR_CHAUD
        tendance = f"↓ {n.delta_30j_m:.2f} m/30 j"
    else:
        couleur_tend = COULEUR_NEUTRE
        tendance = "→ stable/30 j"
    amplitude = n.max_saison_ngf - n.min_saison_ngf
    ecart_pct_niveau = (
        round((n.niveau_ngf - n.mediane_saison_ngf) / amplitude * 100) if amplitude else 0
    )
    signe_niveau = "+" if ecart_pct_niveau >= 0 else ""
    img_b64 = base64.b64encode(graphe_nappe(n)).decode()
    img_html = (
        f'<img src="data:image/png;base64,{img_b64}" '
        'style="width:100%;max-width:500px;display:block;margin:6px 0 4px;" alt="">'
    )
    corps = (
        f'<div style="font-size:18px;font-weight:700;color:{couleur};margin-bottom:4px;">'
        f"{n.classe_saison.capitalize()} ({signe_niveau}{ecart_pct_niveau} %)"
        f'<span style="color:#2c3e50;font-weight:400;"> · </span>'
        f'<span style="color:{couleur_tend};font-weight:400;">{tendance}</span></div>'
        f"{img_html}"
        f'<div style="color:#888;font-size:12px;margin-top:4px;">'
        f"% = (niveau − médiane) / (max − min) × 100</div>"
    )
    titre = f"État de la nappe au {n.date_mesure.strftime('%d/%m/%Y')} — {b.nom_station_nappe}"
    return _carte(titre, couleur, corps)


def _bloc_pluie(b: BulletinEau) -> str:
    p = b.pluie
    if p is None:
        return ""
    if p.classe == "déficitaire":
        couleur = COULEUR_CHAUD
    elif p.classe == "excédentaire":
        couleur = COULEUR_PLUIE
    else:
        couleur = COULEUR_NEUTRE
    signe = "+" if p.ecart_pct >= 0 else ""
    titre = (
        f"Pluie sur {p.debut.strftime('%d/%m')}–{p.fin.strftime('%d/%m/%Y')}"
        f" / normale — Pleine-Fougères"
    )
    img_b64 = base64.b64encode(graphe_pluie(p)).decode()
    img_html = (
        f'<img src="data:image/png;base64,{img_b64}" '
        'style="width:100%;max-width:500px;display:block;margin:6px 0 4px;" alt="">'
    )
    corps = (
        f'<div style="font-size:18px;font-weight:700;color:{couleur};margin-bottom:4px;">'
        f"{p.classe.capitalize()} ({signe}{p.ecart_pct} %)</div>"
        f"{img_html}"
        f'<div style="color:#888;font-size:12px;margin-top:4px;">'
        f"% = (cumul − normale) / normale × 100</div>"
    )
    return _carte(titre, couleur, corps)


# ----- Sujet / texte / HTML -----


def composer_sujet(b: BulletinEau) -> str:
    d = b.genere_le
    mois = MOIS_FR[d.month - 1]
    bouts: list[str] = []
    if b.nappe is not None:
        bouts.append(f"nappe {b.nappe.classe_saison}")
    if b.pluie is not None:
        bouts.append(f"pluie {b.pluie.classe}")
    suffixe = f" — {', '.join(bouts)}" if bouts else ""
    return f"Bulletin eau {mois} {d.year}{suffixe}"


def composer_texte(b: BulletinEau) -> str:
    lignes = [composer_sujet(b), "=" * 48, ""]
    if b.nappe is not None:
        n = b.nappe
        lignes += [
            f"ÉTAT DE LA NAPPE À {b.nom_station_nappe.upper()}",
            f"  Niveau {n.classe_saison} pour la saison : {n.niveau_ngf:.2f} m "
            f"({n.percentile_saison}e percentile de {MOIS_FR[n.mois - 1]}, "
            f"{n.n_annees_saison} ans)",
            f"  Mesure du {n.date_mesure.strftime('%d/%m/%Y')} ({n.age_jours} j)",
            "",
        ]
    if b.pluie is not None:
        p = b.pluie
        signe = "+" if p.ecart_mm >= 0 else ""
        lignes += [
            f"PLUIE {p.fenetre_jours} J vs NORMALE : {p.cumul_mm:.0f} mm "
            f"({signe}{p.ecart_pct} % vs {p.normale_mm:.0f} mm) — {p.classe}",
            "",
        ]
    bsh_date = (b.genere_le - pd.DateOffset(months=2)).replace(day=1)
    bsh_url = (
        "https://www.centre-val-de-loire.developpement-durable.gouv.fr/IMG/pdf/"
        f"{bsh_date.year}_{bsh_date.month:02d}_bsh_bassin_loire_bretagne.pdf"
    )
    mf_debut = b.genere_le.replace(day=1)
    mf_fin = (b.genere_le + pd.DateOffset(months=2)).replace(day=1)
    m1, m2 = MOIS_FR[mf_debut.month - 1], MOIS_FR[mf_fin.month - 1]
    if mf_debut.year == mf_fin.year:
        mf_periode = f"{m1}–{m2} {mf_debut.year}"
    else:
        mf_periode = f"{m1} {mf_debut.year}–{m2} {mf_fin.year}"
    bsh_mois = MOIS_FR[bsh_date.month - 1]
    lignes += [
        "POUR ANTICIPER LE MOIS À VENIR",
        f"  • Prévision saisonnière Météo-France — T° et précip. {mf_periode} :",
        "    https://meteofrance.fr/actualite/publications/les-tendances-climatiques-trois-mois",
        f"  • Bulletin de Situation Hydrologique Loire-Bretagne — {bsh_mois} {bsh_date.year} :",
        f"    {bsh_url}",
        "",
        "Sources : Hub'Eau (piézométrie ADES), ERA5 via CDS ECMWF (pluie).",
    ]
    return "\n".join(lignes)


def composer_html(b: BulletinEau) -> str:
    d = b.genere_le
    titre = f"Bulletin eau — {MOIS_FR[d.month - 1]} {d.year}"
    blocs = "".join(bloc for bloc in (_bloc_nappe(b), _bloc_pluie(b)) if bloc)
    if not blocs:
        blocs = (
            '<div style="color:#888;font-style:italic;">Aucune donnée disponible '
            "ce mois-ci (sources momentanément indisponibles).</div>"
        )
    # BSH Loire-Bretagne : publié vers le 15 du mois, notre bulletin tourne le 1er
    # → le plus récent disponible est celui d'il y a 2 mois.
    bsh_date = (d - pd.DateOffset(months=2)).replace(day=1)
    bsh_url = (
        "https://www.centre-val-de-loire.developpement-durable.gouv.fr/IMG/pdf/"
        f"{bsh_date.year}_{bsh_date.month:02d}_bsh_bassin_loire_bretagne.pdf"
    )
    bsh_label = (
        f"Bulletin de Situation Hydrologique Loire-Bretagne"
        f" — {MOIS_FR[bsh_date.month - 1]} {bsh_date.year}"
    )
    # Trimestre MF : mois courant → mois courant + 2
    mf_debut = d.replace(day=1)
    mf_fin = (d + pd.DateOffset(months=2)).replace(day=1)
    m1, m2 = MOIS_FR[mf_debut.month - 1], MOIS_FR[mf_fin.month - 1]
    if mf_debut.year == mf_fin.year:
        mf_periode = f"{m1}–{m2} {mf_debut.year}"
    else:
        mf_periode = f"{m1} {mf_debut.year}–{m2} {mf_fin.year}"
    corps_anticiper = (
        '<ul style="margin:4px 0 0 0;padding-left:18px;line-height:1.8;">'
        "<li>"
        '<a href="https://meteofrance.fr/actualite/publications/'
        'les-tendances-climatiques-trois-mois" '
        'style="color:#2980b9;text-decoration:none;">'
        f"Prévision saisonnière Météo-France — T° et précip. {mf_periode}"
        "</a></li>"
        "<li>"
        f'<a href="{bsh_url}" style="color:#2980b9;text-decoration:none;">'
        f"{bsh_label}</a></li>"
        "</ul>"
    )
    bloc_anticiper = _carte("Pour anticiper le mois à venir", COULEUR_NEUTRE, corps_anticiper)
    footer = (
        '<div style="font-size:11px;color:#aaa;margin-top:18px;'
        'border-top:1px solid #eee;padding-top:10px;line-height:1.5;">'
        f"Généré le {d.strftime('%d/%m/%Y')}. Sources : Hub'Eau (piézométrie ADES), "
        "ERA5 via CDS ECMWF (pluie)."
        "</div>"
    )
    return (
        '<div style="max-width:560px;margin:0 auto;font-family:-apple-system,'
        "BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#34495e;"
        'padding:8px;">'
        f'<h2 style="font-size:20px;color:#2c3e50;margin:0 0 4px 0;">{titre}</h2>'
        '<div style="font-size:13px;color:#888;margin-bottom:14px;">'
        "La Petite Claye, Pleine-Fougères</div>"
        f"{blocs}{bloc_anticiper}{footer}"
        "</div>"
    )


def composer_bulletin_email(b: BulletinEau) -> EmailComposed:
    """Triplet sujet/texte/html prêt pour ``apps.veille.sender.envoyer``."""
    return EmailComposed(
        sujet=composer_sujet(b),
        texte=composer_texte(b),
        html=composer_html(b),
    )
