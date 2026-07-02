"""Composition de l'email du bulletin eau mensuel (texte + HTML).

Mobile-first, styles inline (compatibilité clients mail). Trois blocs
optionnels — nappe, restrictions, pluie — rendus seulement si la donnée
est présente. Ton informationnel : on **expose l'état**, on n'enjoint
rien (le proxy nappe n'est pas le forage, c'est rappelé en clair).

Réutilise ``EmailComposed`` (triplet sujet/texte/html) de la Veille pour
rester compatible avec ``apps.veille.sender``.
"""

from __future__ import annotations

from apps.shared.dates_fr import MOIS_FR
from apps.shared.style import (
    COULEUR_CHAUD,
    COULEUR_NEUTRE,
    COULEUR_PLUIE,
)
from apps.veille.email import EmailComposed

from .donnees import BulletinEau
from .vocabulaire import couleur_classe_nappe, couleur_niveau_restriction

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
    prof = f" (≈ {n.profondeur_m:.1f} m sous le sol)" if n.profondeur_m is not None else ""
    if n.delta_30j_m is None:
        tendance = "tendance récente indisponible"
    elif n.delta_30j_m > 0.05:
        tendance = f"en hausse (+{n.delta_30j_m:.2f} m sur ~30 j)"
    elif n.delta_30j_m < -0.05:
        tendance = f"en baisse ({n.delta_30j_m:.2f} m sur ~30 j)"
    else:
        tendance = "stable sur ~30 j"

    corps = (
        f"Niveau <b>{n.classe_saison}</b> pour la saison — "
        f"<b>{n.niveau_ngf:.2f} m NGF</b>{prof}, "
        f"au <b>{n.percentile_saison}<sup>e</sup> percentile</b> des mois de "
        f"{MOIS_FR[n.mois - 1]} sur {n.n_annees_saison} ans "
        f"(médiane {n.mediane_saison_ngf:.2f} ; plage {n.min_saison_ngf:.2f}–"
        f"{n.max_saison_ngf:.2f} m NGF).<br>"
        f"Nappe {tendance}.<br>"
        f'<span style="color:#888;font-size:12px;">Mesure du '
        f"{n.date_mesure.strftime('%d/%m/%Y')} ({n.age_jours} j) · plus bas du suivi : "
        f"{n.plus_bas_ngf:.2f} m NGF le {n.plus_bas_date.strftime('%d/%m/%Y')}.</span>"
    )
    corps += _ligne_caveat(
        f"Proxy de tendance régionale ({b.nom_station_nappe}) — pas le débit de votre forage."
    )
    return _carte("État de la nappe", couleur, corps)


def _bloc_restrictions(b: BulletinEau) -> str:
    r = b.restrictions
    if r is None:
        return ""
    couleur = couleur_niveau_restriction(r.niveau_max)
    if not r.zones:
        corps = (
            "<b>Aucune restriction sécheresse en vigueur</b> sur la commune "
            "à ce jour (eaux souterraines, superficielles et potable)."
        )
        return _carte("Restrictions sécheresse", couleur, corps)

    from meteo_socle.sources.vigieau import LABELS_NIVEAU, LABELS_TYPE

    items = "".join(
        f"<li><b>{LABELS_TYPE.get(z.type_ressource, z.type_ressource)}</b> : "
        f"{LABELS_NIVEAU.get(z.niveau, z.niveau)}"
        f"{f' — {z.nom_zone}' if z.nom_zone else ''}</li>"
        for z in r.zones
    )
    corps = (
        f"Niveau le plus sévère en vigueur : <b>{r.niveau_max_label}</b>."
        f'<ul style="margin:6px 0 0 0;padding-left:18px;">{items}</ul>'
    )
    if r.niveau_max in ("alerte", "alerte_renforcee", "crise"):
        corps += _ligne_caveat(
            "En maraîchage (« cultures spéciales »), le goutte-à-goutte / la "
            "micro-aspersion lèvent l'interdiction horaire jusqu'au niveau alerte "
            "renforcée. Vérifier l'arrêté préfectoral en vigueur."
        )
    return _carte("Restrictions sécheresse", couleur, corps)


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
    signe = "+" if p.ecart_mm >= 0 else ""
    corps = (
        f"Sur les <b>{p.fenetre_jours} derniers jours</b> "
        f"({p.debut.strftime('%d/%m')}–{p.fin.strftime('%d/%m/%Y')}) : "
        f"<b>{p.cumul_mm:.0f} mm</b>, soit un cumul <b>{p.classe}</b> "
        f"({signe}{p.ecart_mm:.0f} mm, {signe}{p.ecart_pct} %) "
        f"par rapport à la normale {p.ref_debut_annee}-{p.ref_fin_annee} "
        f"({p.normale_mm:.0f} mm)."
    )
    corps += _ligne_caveat(
        "Écart à la normale (réanalyse ERA5/ERA5T), contexte de recharge — pas un indice normalisé."
    )
    return _carte("Pluie récente vs normale", couleur, corps)


# ----- Sujet / texte / HTML -----


def composer_sujet(b: BulletinEau) -> str:
    d = b.genere_le
    mois = MOIS_FR[d.month - 1]
    bouts: list[str] = []
    if b.nappe is not None:
        bouts.append(f"nappe {b.nappe.classe_saison}")
    if b.restrictions is not None:
        if b.restrictions.zones:
            bouts.append(f"restriction {b.restrictions.niveau_max_label.lower()}")
        else:
            bouts.append("sans restriction")
    suffixe = f" — {', '.join(bouts)}" if bouts else ""
    return f"Bulletin eau {mois} {d.year}{suffixe}"


def composer_texte(b: BulletinEau) -> str:
    lignes = [composer_sujet(b), "=" * 48, ""]
    if b.nappe is not None:
        n = b.nappe
        lignes += [
            "ÉTAT DE LA NAPPE (proxy régional, pas le forage)",
            f"  Niveau {n.classe_saison} pour la saison : {n.niveau_ngf:.2f} m NGF "
            f"({n.percentile_saison}e percentile de {MOIS_FR[n.mois - 1]}, "
            f"{n.n_annees_saison} ans)",
            f"  Mesure du {n.date_mesure.strftime('%d/%m/%Y')} ({n.age_jours} j)",
            "",
        ]
    if b.restrictions is not None:
        r = b.restrictions
        if r.zones:
            lignes += [f"RESTRICTIONS SÉCHERESSE : {r.niveau_max_label}", ""]
        else:
            lignes += ["RESTRICTIONS SÉCHERESSE : aucune en vigueur", ""]
    if b.pluie is not None:
        p = b.pluie
        signe = "+" if p.ecart_mm >= 0 else ""
        lignes += [
            f"PLUIE {p.fenetre_jours} J vs NORMALE : {p.cumul_mm:.0f} mm "
            f"({signe}{p.ecart_pct} % vs {p.normale_mm:.0f} mm) — {p.classe}",
            "",
        ]
    lignes += [
        "Sources : Hub'Eau (piézométrie), VigiEau (restrictions), Open-Meteo / ERA5 (pluie).",
    ]
    return "\n".join(lignes)


def composer_html(b: BulletinEau) -> str:
    d = b.genere_le
    titre = f"Bulletin eau — {MOIS_FR[d.month - 1]} {d.year}"
    blocs = "".join(
        bloc for bloc in (_bloc_nappe(b), _bloc_restrictions(b), _bloc_pluie(b)) if bloc
    )
    if not blocs:
        blocs = (
            '<div style="color:#888;font-style:italic;">Aucune donnée disponible '
            "ce mois-ci (sources momentanément indisponibles).</div>"
        )
    footer = (
        '<div style="font-size:11px;color:#aaa;margin-top:18px;'
        'border-top:1px solid #eee;padding-top:10px;line-height:1.5;">'
        f"Généré le {d.strftime('%d/%m/%Y')}. État de la ressource — observation, "
        "sans prévision saisonnière. Sources : Hub'Eau (piézométrie ADES), "
        "VigiEau (restrictions sécheresse), ERA5 via CDS ECMWF (pluie)."
        "</div>"
    )
    return (
        '<div style="max-width:560px;margin:0 auto;font-family:-apple-system,'
        "BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#34495e;"
        'padding:8px;">'
        f'<h2 style="font-size:20px;color:#2c3e50;margin:0 0 4px 0;">{titre}</h2>'
        '<div style="font-size:13px;color:#888;margin-bottom:14px;">'
        "La Petite Claye, Pleine-Fougères</div>"
        f"{blocs}{footer}"
        "</div>"
    )


def composer_bulletin_email(b: BulletinEau) -> EmailComposed:
    """Triplet sujet/texte/html prêt pour ``apps.veille.sender.envoyer``."""
    return EmailComposed(
        sujet=composer_sujet(b),
        texte=composer_texte(b),
        html=composer_html(b),
    )
