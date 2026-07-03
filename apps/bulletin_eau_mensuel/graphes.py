"""Graphes schématiques pour le bulletin eau (PNG → data-URI → CID via sender).

Deux graphes indépendants :
- graphe_nappe  : KDE des niveaux historiques du même mois + annotations
- graphe_pluie  : KDE des cumuls 90 j de référence + annotations
"""

from __future__ import annotations

import io

import numpy as np

from apps.bulletin_eau_mensuel.donnees import AnomaliePluie
from apps.shared.dates_fr import MOIS_FR
from meteo_socle.sources.hubeau_piezo import EtatNappe

_CHAUD = "#D55E00"
_NEUTRE = "#7f8c8d"
_PLUIE = "#0072B2"
_FOND = "#f8f8f8"
_GRIS = "#888888"

_W = 5.0  # largeur pouces
_H = 3.0  # hauteur pouces


def _couleur_classe(classe: str) -> str:
    if classe in ("bas", "déficitaire"):
        return _CHAUD
    if classe in ("haut", "excédentaire"):
        return _PLUIE
    return _NEUTRE


def graphe_nappe(n: EtatNappe) -> bytes:
    """KDE mensuelle (colorée) + KDE annuelle (arrière-plan) + niveau actuel."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.stats import gaussian_kde

    nom_mois = MOIS_FR[n.mois - 1]

    arr_m = np.array(n.valeurs_historiques_mois, dtype=float)
    arr_a = np.array(n.valeurs_historiques_annee, dtype=float)

    x_min = n.plus_bas_ngf
    x_max = n.plus_haut_ngf
    x = np.linspace(x_min, x_max, 600)

    kde_m = gaussian_kde(arr_m, bw_method="silverman")
    y_m = kde_m(x)
    kde_a = gaussian_kde(arr_a, bw_method="silverman")
    y_a = kde_a(x)

    # Normalisation : intégrale = 1 sur la fenêtre affichée
    y_m = y_m / np.trapezoid(y_m, x)
    y_a = y_a / np.trapezoid(y_a, x)
    ymax = float(max(y_m.max(), y_a.max()))

    t33 = float(np.percentile(arr_m, 33))
    t67 = float(np.percentile(arr_m, 67))
    # Couleur alignée sur les terciles du graphe
    couleur = _CHAUD if n.niveau_ngf <= t33 else (_PLUIE if n.niveau_ngf >= t67 else _NEUTRE)
    dx = x_max - x_min

    fig, ax = plt.subplots(figsize=(_W, _H))
    fig.patch.set_facecolor(_FOND)
    ax.set_facecolor(_FOND)

    # Distribution annuelle (arrière-plan, grise)
    ax.fill_between(x, y_a, alpha=0.10, color=_GRIS, linewidth=0)
    ax.plot(x, y_a, color=_GRIS, linewidth=0.9, ls="--", label="Toute l'année")

    # Distribution mensuelle (avant-plan, colorée par terciles)
    for x0, x1, c in [(x_min, t33, _CHAUD), (t33, t67, _NEUTRE), (t67, x_max, _PLUIE)]:
        mask = (x >= x0) & (x <= x1)
        ax.fill_between(x[mask], y_m[mask], alpha=0.22, color=c, linewidth=0)
    ax.plot(x, y_m, color=_NEUTRE, linewidth=1.2, label=nom_mois.capitalize())

    # Légende compacte
    ax.legend(fontsize=7.5, framealpha=0.7, loc="upper right", handlelength=1.4)

    # --- Min / max sous l'axe (extrêmes all-time = annuelle) ---
    y_sub = -ymax * 0.12
    for val, date, lbl, ha in [
        (n.plus_bas_ngf, n.plus_bas_date, "min", "left"),
        (n.plus_haut_ngf, n.plus_haut_date, "max", "right"),
    ]:
        ax.plot(val, 0, marker="|", color=_GRIS, markersize=6, markeredgewidth=1.2)
        ax.text(
            val,
            y_sub,
            f"{lbl} = {val:.1f} m\n{date.strftime('%d/%m/%Y')}",
            color=_GRIS,
            ha=ha,
            va="top",
            fontsize=7.5,
            linespacing=1.3,
        )

    # Médiane mensuelle (trait pointillé + label à droite)
    ax.axvline(n.mediane_saison_ngf, color=_GRIS, lw=0.8, ls="--")
    ax.plot(n.mediane_saison_ngf, 0, marker="|", color=_GRIS, markersize=6, markeredgewidth=1.2)
    ax.text(
        n.mediane_saison_ngf + dx * 0.015,
        y_sub,
        f"méd. {nom_mois} = {n.mediane_saison_ngf:.1f} m",
        color=_GRIS,
        ha="left",
        va="top",
        fontsize=7.5,
    )

    # --- Ligne du niveau actuel ---
    ax.axvline(n.niveau_ngf, color=couleur, lw=2.0, zorder=5)
    ha_val = "left" if n.niveau_ngf <= n.mediane_saison_ngf else "right"
    off_val = dx * 0.02 if ha_val == "left" else -dx * 0.02
    ax.text(
        n.niveau_ngf + off_val,
        ymax * 1.04,
        f"{n.niveau_ngf:.1f} m",
        color=couleur,
        ha=ha_val,
        va="bottom",
        fontsize=9,
        fontweight="bold",
        clip_on=False,
    )

    # --- Double flèche niveau → médiane ---
    ecart = n.niveau_ngf - n.mediane_saison_ngf
    abs_ecart = abs(round(ecart, 1))
    sens = "sous" if ecart < 0 else "au-dessus de"
    arrow_y = ymax * 0.06
    ax.annotate(
        "",
        xy=(n.mediane_saison_ngf, arrow_y),
        xytext=(n.niveau_ngf, arrow_y),
        arrowprops=dict(arrowstyle="<->", color=couleur, lw=1.2, mutation_scale=8),
    )
    ax.text(
        n.niveau_ngf + off_val,
        arrow_y + ymax * 0.05,
        f"−{abs_ecart:.1f} m {sens} la méd.",
        color=couleur,
        ha=ha_val,
        va="bottom",
        fontsize=8.5,
    )

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-ymax * 0.42, ymax * 1.18)
    ax.set_xlabel(
        f"Niveau (m NGF) · {nom_mois} : {n.n_annees_saison} ans",
        fontsize=8,
        color=_GRIS,
    )
    ax.tick_params(labelsize=7.5, colors=_GRIS)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.yaxis.set_visible(False)
    ax.spines["bottom"].set_edgecolor(_GRIS)
    fig.tight_layout(pad=0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor=_FOND)
    plt.close(fig)
    return buf.getvalue()


def graphe_pluie(p: AnomaliePluie) -> bytes:
    """KDE saisonnière (colorée) + KDE annuelle (arrière-plan) + cumul actuel."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.stats import gaussian_kde

    nom_mois = MOIS_FR[p.fin.month - 1]

    arr_s = np.array(p.sommes_ref, dtype=float)
    arr_a = np.array(p.sommes_ref_annee, dtype=float)

    # Bornes X : percentiles de la distribution annuelle (1-99 si n ≥ 100, sinon 5-95)
    p_lo, p_hi = (1, 99) if len(arr_a) >= 100 else (5, 95)
    x_min = min(float(np.percentile(arr_a, p_lo)), p.cumul_mm) - 5
    x_max = max(float(np.percentile(arr_a, p_hi)), p.cumul_mm) + 5

    x = np.linspace(x_min, x_max, 600)

    kde_s = gaussian_kde(arr_s, bw_method="silverman")
    y_s = kde_s(x)
    kde_a = gaussian_kde(arr_a, bw_method="silverman")
    y_a = kde_a(x)

    # Normalisation : intégrale = 1 sur la fenêtre affichée
    y_s = y_s / np.trapezoid(y_s, x)
    y_a = y_a / np.trapezoid(y_a, x)
    ymax = float(max(y_s.max(), y_a.max()))

    t33 = float(np.percentile(arr_s, 33))
    t67 = float(np.percentile(arr_s, 67))
    # Couleur alignée sur les terciles du graphe
    couleur = _CHAUD if p.cumul_mm <= t33 else (_PLUIE if p.cumul_mm >= t67 else _NEUTRE)

    fig, ax = plt.subplots(figsize=(_W, _H))
    fig.patch.set_facecolor(_FOND)
    ax.set_facecolor(_FOND)

    # Distribution annuelle (arrière-plan, grise)
    ax.fill_between(x, y_a, alpha=0.10, color=_GRIS, linewidth=0)
    ax.plot(x, y_a, color=_GRIS, linewidth=0.9, ls="--", label="Toute l'année")

    # Distribution saisonnière (avant-plan, colorée par terciles)
    for x0, x1, c in [(x_min, t33, _CHAUD), (t33, t67, _NEUTRE), (t67, x_max, _PLUIE)]:
        mask = (x >= x0) & (x <= x1)
        ax.fill_between(x[mask], y_s[mask], alpha=0.22, color=c, linewidth=0)
    ax.plot(x, y_s, color=_NEUTRE, linewidth=1.2, label=f"Fin {nom_mois}")

    ax.legend(fontsize=7.5, framealpha=0.7, loc="upper right", handlelength=1.4)

    dx_p = x_max - x_min

    # --- Cumul actuel ---
    ax.axvline(p.cumul_mm, color=couleur, lw=2.0, zorder=5)
    # Valeur : à droite si bas (intérieur), à gauche si haut
    ha_val = "left" if p.cumul_mm <= p.normale_mm else "right"
    off_val = dx_p * 0.02 if ha_val == "left" else -dx_p * 0.02
    ax.text(
        p.cumul_mm + off_val,
        ymax * 1.04,
        f"{p.cumul_mm:.0f} mm",
        color=couleur,
        ha=ha_val,
        va="bottom",
        fontsize=9,
        fontweight="bold",
        clip_on=False,
    )

    # --- Normale : trait pointillé + valeur sous l'axe (à droite du trait) ---
    ax.axvline(p.normale_mm, color=_GRIS, lw=0.8, ls="--")
    ax.plot(p.normale_mm, 0, marker="|", color=_GRIS, markersize=6, markeredgewidth=1.2)
    ax.text(
        p.normale_mm + dx_p * 0.015,
        -ymax * 0.12,
        f"norm. = {p.normale_mm:.0f} mm\n{p.ref_debut_annee}–{p.ref_fin_annee}",
        color=_GRIS,
        ha="left",
        va="top",
        fontsize=7.5,
        linespacing=1.3,
    )

    # --- Double flèche cumul → normale (écart seul, sans percentile) ---
    abs_ecart = abs(round(p.ecart_mm))
    sens = "sous" if p.ecart_mm < 0 else "au-dessus de"
    arrow_y = ymax * 0.06
    ax.annotate(
        "",
        xy=(p.normale_mm, arrow_y),
        xytext=(p.cumul_mm, arrow_y),
        arrowprops=dict(arrowstyle="<->", color=couleur, lw=1.2, mutation_scale=8),
    )
    ax.text(
        p.cumul_mm + off_val,
        arrow_y + ymax * 0.05,
        f"−{abs_ecart} mm {sens} la norm.",
        color=couleur,
        ha=ha_val,
        va="bottom",
        fontsize=8.5,
    )

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-ymax * 0.42, ymax * 1.18)
    n_ans = p.ref_fin_annee - p.ref_debut_annee + 1
    fin_mois = MOIS_FR[p.fin.month - 1]
    ax.set_xlabel(
        f"Cumul {p.fenetre_jours} j fin {fin_mois} (mm) · {n_ans} ans de référence",
        fontsize=8,
        color=_GRIS,
    )
    ax.tick_params(labelsize=7.5, colors=_GRIS)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.yaxis.set_visible(False)
    ax.spines["bottom"].set_edgecolor(_GRIS)
    fig.tight_layout(pad=0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor=_FOND)
    plt.close(fig)
    return buf.getvalue()
