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


COURBES: list[CourbeConfig] = [
    CourbeConfig(
        colonne="t_min_celsius",
        colonne_normale="t_min_normale_celsius",
        titre="Température minimale",
        unite="°C",
        couleur="#2980b9",
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
    """
    fig, ax = plt.subplots(figsize=figsize)
    x = quotidien.index
    y = quotidien[cfg.colonne]

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
