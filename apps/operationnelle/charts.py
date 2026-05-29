"""Figures matplotlib pour l'App 2 Op — courbes 7 j avec overlay normale.

Pour chaque indicateur, une figure :

- Courbe prévision (couleur indicateur)
- Si normale disponible : courbe normale (gris pointillé) + zone ombrée
  entre les deux (vert = excédent ou plus chaud, rouge = déficit ou
  plus froid selon la sémantique de l'indicateur).

Bilan hydrique :
- Plein champ : ``figure_bilan_culture`` — simple cumul pluie vs ETc.
- Sous tunnel : ``figure_bilan_tunnel`` — modèle sol complet via
  ``meteo_socle.indices.bilan_hydrique.calcul_bilan`` itéré jour par
  jour avec carry-over RU. Pluie = 0 (couverture), ETP × k_tunnel.

Séparé de ``streamlit_app.py`` pour rester testable sans runtime UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import matplotlib.pyplot as plt
import pandas as pd

# Sémantique : si valeur > normale, couleur "above" ; sinon "below".
COULEUR_ABOVE_CHAUD = "#e74c3c"  # rouge — au-dessus de la normale en T°
COULEUR_BELOW_FROID = "#3498db"  # bleu — en-dessous de la normale en T°
COULEUR_NORMALE = "#888888"

# Seuil Smith (ADR-0007) : 11 h / jour sur 2 jours consécutifs.
SMITH_HEURES_MIN = 11
SMITH_FENETRE_J = 2


@dataclass
class Seuil:
    """Seuil informatif tracé en horizontal pointillé sur une courbe.

    **Affiché seulement si la courbe traverse ce seuil dans la fenêtre
    visible** (sinon bruit visuel : un seuil hors range ne porte pas
    d'info).
    """

    valeur: float
    label: str
    couleur: str = "#c0392b"


@dataclass
class CourbeConfig:
    """Configuration de rendu d'un indicateur."""

    colonne: str
    titre: str
    unite: str
    couleur: str
    colonne_normale: str | None = None
    couleur_above: str = COULEUR_ABOVE_CHAUD
    couleur_below: str = COULEUR_BELOW_FROID
    # Liste de seuils statiques (définis ici, indépendants de la config
    # alertes runtime). Pour des seuils dynamiques (gel, canicule), les
    # passer via ``figure_indicateur(seuils_extra=...)``.
    seuils: list[Seuil] = field(default_factory=list)


def _decorer_mildiou_hr(ax, x, y) -> None:
    """Décore l'axe pour l'indicateur Smith h HR ≥ 90 %.

    - Barres = nb d'heures HR ≥ 90 % par jour
    - Ligne pointillée = minimum glissant sur 2 j (input réel Smith)
    - Ligne rouge horizontale = seuil 11 h
    - Shade orange sous les jours où min 2 j ≥ seuil
    """
    y_min2j = y.rolling(window=SMITH_FENETRE_J, min_periods=SMITH_FENETRE_J).min()

    ax.bar(x, y, color="#bdc3c7", width=0.65, label="h HR ≥ 90 % (jour)")
    ax.plot(
        x,
        y_min2j,
        color="#8e44ad",
        linestyle="--",
        linewidth=1.8,
        marker="o",
        markersize=4,
        label=f"Min glissant sur {SMITH_FENETRE_J} j (input Smith)",
    )
    ax.axhline(
        SMITH_HEURES_MIN,
        color="#c0392b",
        linestyle=":",
        linewidth=1.4,
        label=f"Seuil Smith ({SMITH_HEURES_MIN} h)",
    )
    # Shade vertical sur les jours où min 2j ≥ seuil → critère humidité validé.
    qualifie = (y_min2j >= SMITH_HEURES_MIN).fillna(False)
    if qualifie.any():
        # Largeur d'une barre journalière en jours (matplotlib).
        for date_j, q in qualifie.items():
            if q:
                ax.axvspan(
                    date_j - pd.Timedelta(hours=12),
                    date_j + pd.Timedelta(hours=12),
                    color="#e67e22",
                    alpha=0.12,
                )
        # Une seule entrée légende pour le shade.
        from matplotlib.patches import Patch

        h, lbl = ax.get_legend_handles_labels()
        h.append(Patch(facecolor="#e67e22", alpha=0.18, label="Critère humidité Smith validé"))
        ax.legend(handles=h, loc="best", fontsize=8, frameon=False)


COURBES: list[CourbeConfig] = [
    CourbeConfig(
        colonne="t_min_celsius",
        colonne_normale="t_min_normale_celsius",
        titre="Température minimale",
        unite="°C",
        couleur="#2980b9",
        # Seuil statique = filtre biologique Smith (ADR-0007). Le seuil
        # gel (config alertes) est injecté dynamiquement par
        # streamlit_app via seuils_extra.
        seuils=[Seuil(10.0, "Seuil biologique Smith (10 °C)", "#c0392b")],
    ),
    CourbeConfig(
        colonne="t_max_celsius",
        colonne_normale="t_max_normale_celsius",
        titre="Température maximale",
        unite="°C",
        couleur="#c0392b",
    ),
    CourbeConfig(
        colonne="t_moy_celsius",
        colonne_normale="t_moy_normale_celsius",
        titre="Température moyenne",
        unite="°C",
        couleur="#7f8c8d",
    ),
    CourbeConfig(
        colonne="pluie_24h_mm",
        titre="Pluie cumulée 24 h",
        unite="mm",
        couleur="#2980b9",
    ),
    CourbeConfig(
        colonne="etp_mm",
        titre="Évapotranspiration ET₀ (FAO socle)",
        unite="mm",
        couleur="#16a085",
    ),
    CourbeConfig(
        colonne="bilan_eau_cumul_mm",
        titre="Bilan eau cumulé (pluie − ET₀)",
        unite="mm",
        couleur="#8e44ad",
    ),
    CourbeConfig(
        colonne="rafales_max_kmh",
        titre="Rafales max",
        unite="km/h",
        couleur="#d35400",
    ),
    CourbeConfig(
        colonne="mildiou_heures_hr_haute",
        titre="Heures HR ≥ 90 % (mildiou Smith)",
        unite="h",
        couleur="#8e44ad",
    ),
]


def figure_indicateur(
    quotidien: pd.DataFrame,
    cfg: CourbeConfig,
    figsize: tuple[float, float] = (8.0, 3.2),
    seuils_extra: list[Seuil] | None = None,
) -> plt.Figure:
    """Construit une figure matplotlib pour un indicateur donné.

    Si une colonne normale est référencée et présente, overlay
    pointillé + shade entre prévision et normale (sémantique
    chaud/froid selon que la prévision est au-dessus / en-dessous).

    Cas spécial ``mildiou_heures_hr_haute`` (cf. ADR-0007 Smith) :
    on superpose le minimum sur fenêtre glissante 2 j (le vrai input
    de Smith) et le seuil critique 11 h. Une journée n'est partie
    d'une période de Smith que si le min 2 j passe au-dessus du
    seuil — un seul jour à 15 h ne suffit pas.
    """
    fig, ax = plt.subplots(figsize=figsize)
    x = quotidien.index
    y = quotidien[cfg.colonne]

    if cfg.colonne == "mildiou_heures_hr_haute":
        _decorer_mildiou_hr(ax, x, y)
        ax.set_ylabel(cfg.unite)
        ax.set_title(cfg.titre, fontsize=11, loc="left", color="#34495e")
        ax.grid(axis="y", alpha=0.25)
        ax.legend(loc="best", fontsize=8, frameon=False)
        fig.autofmt_xdate(rotation=30, ha="right")
        fig.tight_layout()
        return fig

    has_normale = cfg.colonne_normale is not None and cfg.colonne_normale in quotidien.columns
    if has_normale:
        yn = quotidien[cfg.colonne_normale]
        # Shade between : au-dessus / en-dessous de normale.
        ax.fill_between(
            x,
            y,
            yn,
            where=(y >= yn),
            interpolate=True,
            color=cfg.couleur_above,
            alpha=0.18,
            label="Au-dessus normale",
        )
        ax.fill_between(
            x,
            y,
            yn,
            where=(y < yn),
            interpolate=True,
            color=cfg.couleur_below,
            alpha=0.18,
            label="En-dessous normale",
        )
        ax.plot(
            x,
            yn,
            color=COULEUR_NORMALE,
            linestyle="--",
            linewidth=1.4,
            label="Normale 1991-2020 OMM",
        )

    ax.plot(x, y, color=cfg.couleur, linewidth=2.2, marker="o", label="Prévision")

    # Seuils informatifs (statiques cfg.seuils + dynamiques seuils_extra).
    # Affichés uniquement si la courbe les traverse dans la fenêtre.
    seuils_tous: list[Seuil] = list(cfg.seuils) + list(seuils_extra or [])
    for s in seuils_tous:
        if y.min() < s.valeur < y.max():
            ax.axhline(s.valeur, color=s.couleur, linestyle=":", linewidth=1.4, label=s.label)

    ax.set_ylabel(cfg.unite)
    ax.set_title(cfg.titre, fontsize=11, loc="left", color="#34495e")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="best", fontsize=8, frameon=False)
    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()
    return fig


def bilan_tunnel_carry_over(
    quotidien: pd.DataFrame,
    *,
    k_tunnel: float,
    texture: str,
    fraction_cailloux: float,
    culture: str,
    stade: str,
    fraction_ru_remplie_initial: float,
    ru_vers_rfu: float,
    seuil_irrigation_mm: float,
) -> pd.DataFrame:
    """Calcule le bilan hydrique sous tunnel jour par jour avec carry-over RU.

    Pluie = 0 (couverture). ETP_tunnel = k_tunnel × ETP_extérieur.
    Le calcul socle ``calcul_bilan`` est appliqué chaque jour avec mise
    à jour de ``fraction_ru_remplie`` pour le jour suivant (carry-over),
    comme prescrit dans son docstring.

    Si l'irrigation est déclenchée un jour (besoin > seuil), la RU est
    rechargée jusqu'au plein avant le jour suivant.

    Returns
    -------
    pd.DataFrame
        Indexé comme ``quotidien``, colonnes :
        - ``etp_tunnel_mm`` : ET₀ sous tunnel (k_tunnel × ET₀ socle)
        - ``etm_tunnel_mm`` : ETM = Kc × ET₀_tunnel (positif)
        - ``ru_remplie_avant_mm`` : RU au début du jour
        - ``ru_remplie_apres_mm`` : RU à la fin du jour (après irrigation)
        - ``rfu_disponible_mm`` : RFU disponible début de jour
        - ``besoin_irrigation_mm`` : déficit à combler
        - ``irrigation_declenchee`` : bool (besoin > seuil)
        - ``ru_max_mm`` : capacité RU totale (constante)
    """
    from meteo_socle.indices.bilan_hydrique import (
        KC,
        calcul_reserve_facilement_utilisable,
        calcul_reserve_utile,
    )

    _, _, ru_max, ru_remplie = calcul_reserve_utile(
        texture, fraction_cailloux, culture, fraction_ru_remplie_initial
    )

    kc = float(KC[culture][stade])

    n = len(quotidien)
    etp_tunnel = (k_tunnel * quotidien["etp_mm"]).to_numpy()
    etm_tunnel = kc * etp_tunnel  # positif (consommation par culture)

    ru_avant = []
    ru_apres = []
    rfu_dispo = []
    besoin = []
    irrigue = []
    for i in range(n):
        # Début de journée.
        ru_avant.append(ru_remplie)
        rfu = calcul_reserve_facilement_utilisable(ru_remplie, ru_vers_rfu)
        rfu_dispo.append(rfu)
        rfu_cible = calcul_reserve_facilement_utilisable(ru_max, ru_vers_rfu)
        # Évolution de la RU sur la journée : -ETM (pas de pluie sous tunnel).
        ru_post_jour = max(0.0, ru_remplie - etm_tunnel[i])
        # Besoin pour ramener à la RFU cible.
        rfu_post = calcul_reserve_facilement_utilisable(ru_post_jour, ru_vers_rfu)
        b = max(0.0, rfu_cible - rfu_post)
        besoin.append(b)
        if b > seuil_irrigation_mm:
            ru_remplie = ru_max  # irrigation = recharge complète à capacité champ
            irrigue.append(True)
        else:
            ru_remplie = ru_post_jour
            irrigue.append(False)
        ru_apres.append(ru_remplie)

    return pd.DataFrame(
        {
            "etp_tunnel_mm": etp_tunnel,
            "etm_tunnel_mm": etm_tunnel,
            "ru_remplie_avant_mm": ru_avant,
            "ru_remplie_apres_mm": ru_apres,
            "rfu_disponible_mm": rfu_dispo,
            "besoin_irrigation_mm": besoin,
            "irrigation_declenchee": irrigue,
            "ru_max_mm": [ru_max] * n,
        },
        index=quotidien.index,
    )


def figure_bilan_tunnel(
    bilan: pd.DataFrame,
    culture: str,
    stade: str,
    seuil_irrigation_mm: float,
    figsize: tuple[float, float] = (8.0, 4.0),
) -> plt.Figure:
    """Trace l'évolution de la RU sous tunnel + déclenchements irrigation.

    Deux axes y synchronisés :
    - gauche (mm) : RU disponible (ligne), capacité RU (bande horiz.),
      seuil d'irrigation
    - droite (mm) : besoin d'irrigation par jour (barres)
    - markers verts : jours où l'irrigation est déclenchée
    """
    fig, ax1 = plt.subplots(figsize=figsize)
    ax2 = ax1.twinx()

    x = bilan.index
    ax1.fill_between(
        x,
        0,
        bilan["ru_max_mm"],
        color="#bdc3c7",
        alpha=0.12,
        label="Capacité RU totale",
    )
    ax1.plot(
        x,
        bilan["ru_remplie_avant_mm"],
        color="#2980b9",
        linewidth=2.0,
        marker="o",
        label="RU disponible (début jour)",
    )
    ax1.plot(
        x,
        bilan["rfu_disponible_mm"],
        color="#16a085",
        linewidth=1.2,
        linestyle="--",
        label="RFU disponible",
    )
    ax1.axhline(
        seuil_irrigation_mm,
        color="#c0392b",
        linestyle=":",
        linewidth=1.2,
        label=f"Seuil irrigation ({seuil_irrigation_mm:.0f} mm)",
    )
    # Besoin journalier sur axe droit (barres).
    ax2.bar(
        x,
        bilan["besoin_irrigation_mm"],
        color="#e67e22",
        alpha=0.5,
        width=0.55,
        label="Besoin irrigation (mm)",
    )
    # Markers déclenchements.
    declenche = bilan[bilan["irrigation_declenchee"]]
    if not declenche.empty:
        ax2.scatter(
            declenche.index,
            declenche["besoin_irrigation_mm"],
            color="#27ae60",
            s=60,
            zorder=5,
            label="Irrigation déclenchée",
        )

    ax1.set_ylabel("RU / RFU (mm)")
    ax2.set_ylabel("Besoin irrigation (mm/jour)")
    ax1.set_title(f"Bilan tunnel — {culture} ({stade})", fontsize=11, loc="left", color="#34495e")
    ax1.grid(axis="y", alpha=0.25)

    # Combine légendes des deux axes.
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="best", fontsize=8, frameon=False)

    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()
    return fig


def figure_calendrier_semis(
    cal: list[dict],
    figsize: tuple[float, float] | None = None,
) -> plt.Figure:
    """Gantt timeline horizontale du calendrier semis.

    Parameters
    ----------
    cal :
        Sortie de ``meteo_socle.indices.pepiniere.calendrier_semis``.
    figsize :
        Si None, hauteur adaptative au nombre de cultures.
    """
    if not cal:
        # Figure vide propre.
        fig, ax = plt.subplots(figsize=(8, 1.5))
        ax.text(
            0.5,
            0.5,
            "Aucune culture sélectionnée",
            ha="center",
            va="center",
            transform=ax.transAxes,
            color="#888",
            fontsize=11,
            style="italic",
        )
        ax.axis("off")
        return fig

    n = len(cal)
    if figsize is None:
        figsize = (9.0, max(2.5, 0.35 * n + 1.0))

    # Tri par date semis pour lecture naturelle.
    cal_tri = sorted(cal, key=lambda e: e["date_semis"])
    cultures = [e["culture"] for e in cal_tri]
    semis = [e["date_semis"] for e in cal_tri]
    plant = [e["date_plantation"] for e in cal_tri]

    fig, ax = plt.subplots(figsize=figsize)
    y_pos = list(range(n))

    for i, (s, p) in enumerate(zip(semis, plant, strict=False)):
        # Barre verte = élevage.
        ax.barh(i, (p - s).days, left=s, height=0.55, color="#27ae60", alpha=0.55, edgecolor="none")
        # Marker semis (cercle bleu).
        ax.scatter(s, i, color="#2980b9", s=80, zorder=5, label="Semis" if i == 0 else None)
        # Marker plantation (carré rouge).
        ax.scatter(
            p,
            i,
            color="#c0392b",
            s=80,
            marker="s",
            zorder=5,
            label="Plantation" if i == 0 else None,
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(cultures)
    ax.invert_yaxis()  # première culture en haut.
    ax.set_xlabel("Date")
    ax.set_title("Calendrier semis pépinière", fontsize=11, loc="left", color="#34495e")
    ax.grid(axis="x", alpha=0.25)
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()
    return fig


def figure_bilan_culture(
    quotidien: pd.DataFrame,
    culture: str,
    stade: str,
    kc: float,
    figsize: tuple[float, float] = (8.0, 3.2),
) -> plt.Figure:
    """Trace pluie cumulée vs ET_c cumulée (= Kc × ET₀) + bilan ombré.

    Bilan négatif (cumul pluie < cumul ETc) shadé rouge = besoin
    d'apport théorique ; positif bleu = excédent.
    """
    fig, ax = plt.subplots(figsize=figsize)
    x = quotidien.index
    pluie_cum = quotidien["pluie_24h_mm"].cumsum()
    etc_cum = (kc * quotidien["etp_mm"]).cumsum()

    ax.fill_between(
        x,
        pluie_cum,
        etc_cum,
        where=(pluie_cum >= etc_cum),
        interpolate=True,
        color="#3498db",
        alpha=0.18,
        label="Excédent",
    )
    ax.fill_between(
        x,
        pluie_cum,
        etc_cum,
        where=(pluie_cum < etc_cum),
        interpolate=True,
        color="#e74c3c",
        alpha=0.18,
        label="Déficit",
    )
    ax.plot(x, pluie_cum, color="#2980b9", linewidth=2.0, marker="o", label="Pluie cumulée")
    ax.plot(
        x, etc_cum, color="#c0392b", linewidth=2.0, marker="s", label=f"ET_c cumulée (Kc={kc:.2f})"
    )
    ax.set_ylabel("mm cumulés")
    ax.set_title(f"Bilan hydrique — {culture} ({stade})", fontsize=11, loc="left", color="#34495e")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="best", fontsize=8, frameon=False)
    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()
    return fig
