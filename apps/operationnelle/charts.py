"""Figures matplotlib pour l'App 2 Op — courbes 7 j avec overlay normale.

Pour chaque indicateur, une figure :

- Courbe prévision (couleur indicateur)
- Si normale disponible : courbe normale (gris pointillé) + zone ombrée
  entre les deux (vert = excédent ou plus chaud, rouge = déficit ou
  plus froid selon la sémantique de l'indicateur).

Séparé de ``streamlit_app.py`` pour rester testable sans runtime UI.
"""

from __future__ import annotations

from dataclasses import dataclass

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
class CourbeConfig:
    """Configuration de rendu d'un indicateur."""

    colonne: str
    titre: str
    unite: str
    couleur: str
    colonne_normale: str | None = None
    couleur_above: str = COULEUR_ABOVE_CHAUD
    couleur_below: str = COULEUR_BELOW_FROID
    # Seuil informatif tracé en horizontal pointillé. **Affiché seulement
    # si la courbe traverse ce seuil dans la fenêtre visible** (sinon
    # bruit visuel : un seuil hors range ne porte pas d'info).
    seuil: float | None = None
    seuil_label: str | None = None
    seuil_couleur: str = "#c0392b"


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
        # Filtre biologique Smith (ADR-0007) : sous 10 °C, pas de cycle
        # mildiou possible — affiché si la courbe traverse cette barre.
        seuil=10.0,
        seuil_label="Seuil biologique Smith (10 °C)",
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

    # Seuil informatif uniquement si la courbe le traverse réellement.
    if cfg.seuil is not None and y.min() < cfg.seuil < y.max():
        ax.axhline(
            cfg.seuil,
            color=cfg.seuil_couleur,
            linestyle=":",
            linewidth=1.4,
            label=cfg.seuil_label or f"Seuil {cfg.seuil:g}",
        )

    ax.set_ylabel(cfg.unite)
    ax.set_title(cfg.titre, fontsize=11, loc="left", color="#34495e")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="best", fontsize=8, frameon=False)
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
