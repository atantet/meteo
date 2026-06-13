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

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

from apps.shared.dates_fr import JOURS_FR

# Sémantique : si valeur > normale, couleur "above" ; sinon "below".
COULEUR_ABOVE_CHAUD = "#e74c3c"  # rouge — au-dessus de la normale en T°
COULEUR_BELOW_FROID = "#3498db"  # bleu — en-dessous de la normale en T°
COULEUR_NORMALE = "#888888"

# Largeur réservée pour la légende externe (en pouces). Étend la
# figure sans empiéter sur la zone du plot, qui garde donc la même
# largeur visible quel que soit l'onglet (cohérence visuelle).
LARGEUR_LEGENDE_EXTERNE = 3.0
# Largeur ajoutée pour l'axe Y secondaire (twinx) avec son ylabel.
# Compense le « rétrécissement » visuel de la zone du plot quand
# matplotlib place un 2e ylabel à droite (cas Pluie/probabilité).
LARGEUR_AXE_SECONDAIRE = 0.6


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
    # Colonne secondaire à superposer sur la même figure (ex. proba
    # pluie en overlay de la pluie, vent moy en overlay des rafales).
    # Si ``unite_secondaire`` diffère de ``unite``, un axe Y droit est
    # créé via twinx ; sinon, tracé sur le même axe.
    colonne_secondaire: str | None = None
    couleur_secondaire: str = "#888888"
    label_secondaire: str = ""
    unite_secondaire: str = ""


COURBES: list[CourbeConfig] = [
    CourbeConfig(
        colonne="t_min_celsius",
        colonne_normale="t_min_normale_celsius",
        titre="Température minimale",
        unite="°C",
        couleur="#2980b9",
        # Le seuil gel (config alertes) est injecté dynamiquement par
        # streamlit_app via seuils_extra.
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
]


def figure_indicateur(
    quotidien: pd.DataFrame,
    cfg: CourbeConfig,
    figsize: tuple[float, float] = (8.0, 3.2),
    seuils_extra: list[Seuil] | None = None,
    marker: str | None = "auto",
    t_pivot: pd.Timestamp | None = None,
    legende_externe: bool = False,
) -> plt.Figure:
    """Construit une figure matplotlib pour un indicateur donné.

    Si une colonne normale est référencée et présente, overlay
    pointillé + shade entre prévision et normale (sémantique
    chaud/froid selon que la prévision est au-dessus / en-dessous).
    """
    # Si la légende est externe (à droite), on agrandit la figure de
    # `LARGEUR_LEGENDE_EXTERNE` pouces (+ un peu pour l'ylabel de
    # l'axe secondaire éventuel) pour loger la légende sans rétrécir
    # la zone du plot. Ainsi la largeur visible du tracé principal
    # reste identique entre les onglets.
    a_axe_secondaire = (
        cfg.colonne_secondaire is not None
        and bool(cfg.unite_secondaire)
        and cfg.unite_secondaire != cfg.unite
    )
    extra_ax2 = LARGEUR_AXE_SECONDAIRE if a_axe_secondaire else 0.0
    if legende_externe:
        fs_total = (figsize[0] + extra_ax2 + LARGEUR_LEGENDE_EXTERNE, figsize[1])
        rect_plot = (0.0, 0.0, (figsize[0] + extra_ax2) / fs_total[0], 1.0)
    else:
        fs_total = (figsize[0] + extra_ax2, figsize[1])
        rect_plot = None

    fig, ax = plt.subplots(figsize=fs_total)
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

    # Marker auto : actif pour les séries courtes (≤ 30 points = quotidien
    # sur 4-7 j), désactivé pour les séries horaires (96+ points devient
    # illisible avec un marker par point).
    marker_effectif = ("o" if len(x) <= 30 else None) if marker == "auto" else marker
    plot_kwargs_base = {"color": cfg.couleur, "linewidth": 2.2}
    if marker_effectif:
        plot_kwargs_base["marker"] = marker_effectif

    if t_pivot is not None and x.min() < t_pivot < x.max():
        # Split en deux segments : analyses successives du modèle
        # (passé, translucide) et prévision (futur, opaque). Les deux
        # segments partagent une heure (le pivot) pour rester continus.
        # « Analyse » = sortie T+0 du modèle pour chaque heure passée,
        # récupérée via `past_days` d'Open-Meteo (≠ réanalyse ERA5).
        x_archive = x[x <= t_pivot]
        y_archive = y[x <= t_pivot]
        x_prevu = x[x >= t_pivot]
        y_prevu = y[x >= t_pivot]
        ax.plot(x_archive, y_archive, alpha=0.5, label="Analyse", **plot_kwargs_base)
        ax.plot(x_prevu, y_prevu, label="Prévision", **plot_kwargs_base)
        # Shading gris léger sur toute la partie analyse, plus discret
        # qu'un trait vertical et lisible d'un coup d'œil.
        ax.axvspan(x.min(), t_pivot, color="#7f8c8d", alpha=0.07)
    else:
        ax.plot(x, y, label="Prévision", **plot_kwargs_base)

    # Colonne secondaire (proba pluie, vent moy…) — un seul trait
    # pointillé pour ne pas surcharger ; pas de split archive / prévi.
    handles_extra = []
    labels_extra = []
    if cfg.colonne_secondaire and cfg.colonne_secondaire in quotidien.columns:
        y2 = quotidien[cfg.colonne_secondaire]
        label2 = cfg.label_secondaire or cfg.colonne_secondaire
        if cfg.unite_secondaire and cfg.unite_secondaire != cfg.unite:
            # Unité différente → axe Y droit.
            ax2 = ax.twinx()
            (line2,) = ax2.plot(
                x,
                y2,
                color=cfg.couleur_secondaire,
                linewidth=1.4,
                linestyle="--",
                alpha=0.85,
                label=label2,
            )
            ax2.set_ylabel(
                f"{label2} ({cfg.unite_secondaire})",
                color=cfg.couleur_secondaire,
                fontsize=9,
            )
            ax2.tick_params(axis="y", labelcolor=cfg.couleur_secondaire, labelsize=8)
            if cfg.unite_secondaire == "%":
                ax2.set_ylim(0, 100)
            handles_extra.append(line2)
            labels_extra.append(label2)
        else:
            # Même unité → même axe.
            (line2,) = ax.plot(
                x,
                y2,
                color=cfg.couleur_secondaire,
                linewidth=1.4,
                linestyle="--",
                alpha=0.85,
                label=label2,
            )
            handles_extra.append(line2)
            labels_extra.append(label2)

    # Seuils informatifs (statiques cfg.seuils + dynamiques seuils_extra).
    # Affichés uniquement si la courbe les traverse dans la fenêtre.
    seuils_tous: list[Seuil] = list(cfg.seuils) + list(seuils_extra or [])
    for s in seuils_tous:
        if y.min() < s.valeur < y.max():
            ax.axhline(s.valeur, color=s.couleur, linestyle=":", linewidth=1.4, label=s.label)

    ax.set_ylabel(cfg.unite)
    ax.set_title(cfg.titre, fontsize=11, loc="left", color="#34495e")

    # Grille : verticale jour par jour (xticks majeurs à 00 h local
    # de chaque jour) + horizontale habituelle. Format jours abrégés
    # en français (le locale système n'est pas forcément fr_FR sur
    # Streamlit Cloud, donc on construit le label nous-mêmes).
    from apps.shared.dates_fr import JOURS_FR

    def _fmt_jour_fr(x_val, _pos=None) -> str:
        dt = mdates.num2date(x_val)
        return f"{JOURS_FR[dt.weekday()][:3]}. {dt.day:02d}/{dt.month:02d}"

    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(plt.FuncFormatter(_fmt_jour_fr))
    # Sur des séries horaires (>30 points), ticks mineurs toutes les
    # 6 h pour aider la lecture intra-journalière.
    if len(x) > 30:
        ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=(6, 12, 18)))
        ax.grid(which="minor", axis="x", alpha=0.10, linestyle=":")
    ax.grid(which="major", axis="both", alpha=0.30)

    # Légende : combine la série primaire et la colonne secondaire
    # éventuelle, sinon laisse matplotlib gérer.
    handles_prim, labels_prim = ax.get_legend_handles_labels()
    handles_tous = handles_prim + handles_extra
    labels_tous = labels_prim + labels_extra
    if legende_externe:
        ax.legend(
            handles_tous,
            labels_tous,
            bbox_to_anchor=(1.02, 1),
            loc="upper left",
            fontsize=8,
            frameon=False,
        )
    else:
        ax.legend(handles_tous, labels_tous, loc="best", fontsize=8, frameon=False)
    fig.autofmt_xdate(rotation=30, ha="right")
    if rect_plot is not None:
        fig.tight_layout(rect=rect_plot)
    else:
        fig.tight_layout()
    return fig


def bilan_culture_carry_over(
    quotidien: pd.DataFrame,
    *,
    texture: str,
    fraction_cailloux: float,
    culture: str,
    stade: str,
    fraction_ru_remplie_initial: float,
    ru_vers_rfu: float,
    seuil_irrigation_mm: float,
    k_etp_ratio: float = 1.0,
    inclure_pluie: bool = True,
    apport_max_mm: float = float("inf"),
) -> pd.DataFrame:
    """Bilan hydrique culture-spécifique jour par jour avec carry-over RU.

    Modèle FAO 56 itéré avec carry-over de la RU. On laisse le sol se vider ;
    l'irrigation est déclenchée quand l'**épuisement** (``RU_max − RU``) atteint
    la **RFU** (= ``ru_vers_rfu × RU_max``, RAW), et la **dose** ramène le sol à
    la capacité au champ, **plafonnée à ``apport_max_mm``** (lame d'eau journalière
    max du système ; recharge partielle si l'épuisement la dépasse).
    ``seuil_irrigation_mm`` n'est plus le déclencheur mais un garde-fou « dose
    minimale ».

    Deux cas d'usage symétriques :

    - **Plein champ** (défaut) : ``k_etp_ratio=1.0`` et
      ``inclure_pluie=True``. ET₀ = ET₀ socle, pluie prise du forecast.
    - **Sous tunnel** : ``k_etp_ratio=k_tunnel`` (≈ 0.7) et
      ``inclure_pluie=False`` (couverture). Cf. ADR-0008.

    Parameters
    ----------
    quotidien :
        Doit contenir ``etp_mm`` et, si ``inclure_pluie`` actif,
        ``pluie_24h_mm``.
    k_etp_ratio :
        Coefficient appliqué à l'ET₀ pour passer au contexte de la
        culture (1.0 plein champ, < 1 abri).
    inclure_pluie :
        Si True, la pluie 24 h s'ajoute à la RU (à hauteur de
        capacité champ — l'excédent est perdu en drainage).

    Returns
    -------
    pd.DataFrame
        Colonnes : ``etp_culture_mm``, ``etm_mm``, ``pluie_mm``, ``deficit_mm``
        (ETM non couverte par la pluie), ``apport_mm`` (dose d'irrigation
        réellement appliquée), ``ru_remplie_avant_mm`` (carry-in),
        ``ru_disponible_mm`` (RU après météo, avant irrigation),
        ``ru_remplie_apres_mm`` (carry-out), ``irrigation_declenchee``,
        ``ru_max_mm``, ``rfu_mm``.
    """
    from meteo_socle.indices.bilan_hydrique import KC, calcul_reserve_utile

    _, _, ru_max, ru_remplie = calcul_reserve_utile(
        texture, fraction_cailloux, culture, fraction_ru_remplie_initial
    )

    kc = float(KC[culture][stade])
    rfu = ru_vers_rfu * ru_max  # RFU = RAW (FAO 56) — réserve facilement utilisable

    n = len(quotidien)
    etp_culture = (k_etp_ratio * quotidien["etp_mm"]).to_numpy()
    etm = kc * etp_culture
    if inclure_pluie and "pluie_24h_mm" in quotidien.columns:
        pluie = quotidien["pluie_24h_mm"].to_numpy()
    else:
        pluie = [0.0] * n

    ru_avant: list[float] = []
    ru_dispo: list[float] = []
    ru_apres: list[float] = []
    deficit: list[float] = []
    apport: list[float] = []
    irrigue: list[bool] = []
    pluie_log: list[float] = []
    for i in range(n):
        # RU avant le jour (carry-in ; à J0 = RU initiale, état avant le 1er jour).
        ru_avant.append(ru_remplie)
        pluie_i = float(pluie[i])
        pluie_log.append(pluie_i)
        # Déficit du jour = part de l'ETM non couverte par la pluie (≥ 0).
        deficit.append(max(0.0, etm[i] - pluie_i))
        # RU disponible après la météo du jour (avant irrigation) ; au-delà de la
        # capacité au champ → drainage (perdu).
        ru_post = max(0.0, min(ru_max, ru_remplie + (pluie_i - etm[i])))
        ru_dispo.append(ru_post)
        epuisement = ru_max - ru_post
        # FAO 56 : quand l'épuisement (RU_max − RU disponible) atteint la RFU, on
        # recharge le jour même, sans dépasser l'apport maximal du système
        # (``apport_max_mm``, lame d'eau journalière). seuil_irrigation_mm =
        # garde-fou « dose minimale ».
        if epuisement >= rfu and epuisement > seuil_irrigation_mm:
            ru_remplie = ru_post + min(epuisement, apport_max_mm)
            irrigue.append(True)
        else:
            ru_remplie = ru_post
            irrigue.append(False)
        ru_apres.append(ru_remplie)
        # Apport d'irrigation réellement appliqué = recharge (0 si pas d'irrigation).
        apport.append(ru_remplie - ru_post)

    return pd.DataFrame(
        {
            "etp_culture_mm": etp_culture,
            "etm_mm": etm,
            "pluie_mm": pluie_log,
            "deficit_mm": deficit,
            "apport_mm": apport,
            "ru_remplie_avant_mm": ru_avant,
            "ru_disponible_mm": ru_dispo,
            "ru_remplie_apres_mm": ru_apres,
            "irrigation_declenchee": irrigue,
            "ru_max_mm": [ru_max] * n,
            "rfu_mm": [rfu] * n,
        },
        index=quotidien.index,
    )


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
    apport_max_mm: float = float("inf"),
) -> pd.DataFrame:
    """Wrapper rétro-compatible — bilan sol complet sous tunnel.

    Délègue à ``bilan_culture_carry_over`` avec
    ``inclure_pluie=False`` et ``k_etp_ratio=k_tunnel``.
    Conserve les noms de colonnes historiques ``etp_tunnel_mm`` /
    ``etm_tunnel_mm`` pour les tests existants.
    """
    bilan = bilan_culture_carry_over(
        quotidien,
        texture=texture,
        fraction_cailloux=fraction_cailloux,
        culture=culture,
        stade=stade,
        fraction_ru_remplie_initial=fraction_ru_remplie_initial,
        ru_vers_rfu=ru_vers_rfu,
        seuil_irrigation_mm=seuil_irrigation_mm,
        k_etp_ratio=k_tunnel,
        inclure_pluie=False,
        apport_max_mm=apport_max_mm,
    )
    return bilan.rename(columns={"etp_culture_mm": "etp_tunnel_mm", "etm_mm": "etm_tunnel_mm"})


# Police du plot, calée plus petite que le texte de l'app (≈ 14-16 px Streamlit).
_FONT_PLOT = 8


def _labels_jours_fr(index: pd.DatetimeIndex) -> list[str]:
    """Étiquettes ``mar 9/06`` (jour abrégé 3 lettres + j/mm sans zéro de tête)."""
    return [f"{JOURS_FR[d.weekday()][:3]} {d.day}/{d.month:02d}" for d in index]


def _bold_ticks(ax: plt.Axes, en_gras: list[bool]) -> None:
    """Met en gras les étiquettes x des jours où ``en_gras`` est vrai."""
    for tick, gras in zip(ax.get_xticklabels(), en_gras, strict=False):
        if gras:
            tick.set_fontweight("bold")


def figure_bilan_sol_complet(
    bilan: pd.DataFrame,
    *,
    apport_max_mm: float = 25.0,
    figsize: tuple[float, float] = (9.5, 4.2),
) -> plt.Figure:
    """Bilan hydrique FAO 56 en **deux panneaux côte à côte**.

    - **Flux (gauche)** : par jour, **ETM culture** vs **Précipitation + Déficit**
      empilés — le déficit est la part de l'ETM non couverte par la pluie (en
      situation de déficit les deux barres ont la même hauteur). Le déficit
      *cumule* dans le sol ; il ne traduit pas directement la dose d'irrigation.
    - **Réserves (droite)** : RU disponible (ligne) entre la capacité au champ et
      le **seuil RFU (RU − RFU)** ; les **apports d'irrigation** (dose réellement
      appliquée à la recharge) sont en barres sur le **même axe (mm)** — l'apport
      effectif vaut au plus min(apport_max, RU), donc reste sous la capacité au
      champ —, **entre deux jours**. Un point « lendemain » montre la RU résultante
      après l'apport du dernier jour.

    Pas de titre ; étiquettes de jours en français, **gras** le jour d'irrigation.
    """
    fig, (axf, axr) = plt.subplots(1, 2, figsize=figsize, dpi=300)
    n = len(bilan)
    x = np.arange(n)
    irrigation = list(bilan["irrigation_declenchee"])
    ru_max = float(bilan["ru_max_mm"].iloc[0])
    rfu = float(bilan["rfu_mm"].iloc[0])

    # --- Panneau flux (GAUCHE) : ETM vs (Précipitation + Déficit) empilés ---
    etm_col = "etm_mm" if "etm_mm" in bilan.columns else "etm_tunnel_mm"
    etm = bilan[etm_col].to_numpy()
    pluie = bilan["pluie_mm"].to_numpy()
    deficit = bilan["deficit_mm"].to_numpy()
    w = 0.38
    axf.bar(x - w / 2, etm, w, color="#D55E00", label="ETM culture")
    axf.bar(x + w / 2, pluie, w, color="#56B4E9", label="Précipitation")
    axf.bar(x + w / 2, deficit, w, bottom=pluie, color="#009E73", label="Déficit")
    axf.set_ylabel("Flux (mm/jour)", fontsize=_FONT_PLOT)
    axf.set_ylim(bottom=0)
    axf.grid(axis="y", alpha=0.2)
    axf.set_xticks(x)
    axf.set_xticklabels(_labels_jours_fr(bilan.index), fontsize=_FONT_PLOT - 1)
    axf.tick_params(axis="y", labelsize=_FONT_PLOT - 1)
    _bold_ticks(axf, irrigation)
    axf.legend(
        fontsize=_FONT_PLOT,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=3,
    )

    # --- Panneau réserves (DROITE) : RU + seuils, apports sur axe secondaire ---
    # 5ᵉ point « lendemain » : RU au départ du jour suivant = carry-out du dernier
    # jour (montre l'effet de l'apport du dernier jour, sans météo J+5).
    ru_dispo = bilan["ru_disponible_mm"].to_numpy()
    carry_out_last = float(bilan["ru_remplie_apres_mm"].iloc[-1])
    x_ru = np.arange(n + 1)
    y_ru = np.append(ru_dispo, carry_out_last)
    index_plus = [*list(bilan.index), bilan.index[-1] + pd.Timedelta(days=1)]

    # Apports d'irrigation en barres, sur le **même axe (mm)** que la réserve :
    # l'apport effectif vaut au plus min(apport_max, RU) (épuisement ≤ RU), donc il
    # tient sous la capacité au champ — pas d'axe secondaire. (apport_max_mm est déjà
    # appliqué en amont, dans le bilan, sur ``apport_mm``.) zorder : barres dessous,
    # repères au milieu, courbe RU au-dessus.
    apport = bilan["apport_mm"].to_numpy()
    mask = apport > 0
    axr.bar((x + 0.5)[mask], apport[mask], 0.22, color="#009E73", zorder=1)
    axr.axhline(ru_max, color="#95a5a6", linewidth=1.0, label="Capacité au champ", zorder=2)
    axr.axhline(
        ru_max - rfu,
        color="#c0392b",
        linestyle="--",
        linewidth=1.2,
        label="Seuil RFU (RU - RFU)",
        zorder=2,
    )
    axr.plot(
        x_ru, y_ru, color="#0072B2", linewidth=2.0, marker="o", label="RU disponible", zorder=3
    )
    axr.set_ylabel("Réserve utile et apport (mm)", fontsize=_FONT_PLOT)
    axr.set_ylim(0, ru_max * 1.12)
    axr.grid(axis="y", alpha=0.2)
    axr.set_xticks(x_ru)
    axr.set_xticklabels(_labels_jours_fr(index_plus), fontsize=_FONT_PLOT - 1)
    axr.tick_params(axis="y", labelsize=_FONT_PLOT - 1)
    _bold_ticks(axr, [*irrigation, False])

    # Proxy de légende pour l'apport : couleur constante même les jours sans
    # apport (sinon le swatch dépend du BarContainer, vide → incohérent).
    h1, l1 = axr.get_legend_handles_labels()
    apport_proxy = Patch(facecolor="#009E73", label="Apport irrigation")
    axr.legend(
        [*h1, apport_proxy],
        [*l1, "Apport irrigation"],
        fontsize=_FONT_PLOT,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=2,
    )

    # Légendes sous les plots : on réserve de la marge basse sans rétrécir les
    # cadres (figure plus haute), plutôt que tight_layout (qui mangerait l'espace).
    fig.subplots_adjust(left=0.08, right=0.92, top=0.96, bottom=0.32, wspace=0.32)
    return fig


def figure_bilan_tunnel(
    bilan: pd.DataFrame,
    *,
    apport_max_mm: float = 25.0,
    figsize: tuple[float, float] = (9.5, 4.2),
) -> plt.Figure:
    """Sous abri : même figure (la pluie est nulle sous couverture)."""
    return figure_bilan_sol_complet(bilan, apport_max_mm=apport_max_mm, figsize=figsize)


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
    fig, ax = plt.subplots(figsize=figsize, dpi=300)
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
