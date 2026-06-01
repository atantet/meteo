"""Guides de décision pour l'App 2 Opérationnelle.

À partir d'un DataFrame ``quotidien`` (sortie
``calculer_indicateurs_quotidiens``) et d'une config exploitation, produit
une liste de ``GuideDecision`` pour les règles applicables à la période
courante.

Chaque guide porte un drapeau ``active`` :
- ``True``  : le signal météo dépasse le seuil → guide mis en avant.
- ``False`` : la règle est applicable (saison + données disponibles) mais
  le signal n'est pas franchi → guide affiché grisé, avec un titre
  neutre "Pas de … — <valeur observée>" et les sliders d'ajustement
  toujours accessibles (l'utilisateur peut tester d'autres seuils).

Les règles à fenêtre saisonnière retournent ``None`` hors saison (guide
non applicable, donc non affiché).

Vocabulaire :

- **Guide de décision** = ce module ; titre + détail jour-par-jour + sliders.
- **Carte** (sans qualificatif) = carte météo géographique (cf.
  ``apps/operationnelle/cartes_geo.py`` et ``apps/veille/cartes_synoptiques.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from apps.veille.config import REPO_ROOT, _deep_merge, load_yaml

DEFAULT_EXPLOITATION_PATH = REPO_ROOT / "config" / "exploitation.yaml"
LOCAL_EXPLOITATION_OVERRIDE = REPO_ROOT / "config" / "exploitation.local.yaml"

NIVEAU_INFO = "info"
NIVEAU_ANTICIPER = "anticiper"
NIVEAU_CRITIQUE = "critique"

# Thèmes pour le regroupement à l'affichage. Ordre = ordre d'affichage.
THEME_FROID = "froid"
THEME_TUNNEL = "tunnel"
THEME_IRRIGATION = "irrigation"
THEME_TRAVAIL_SOL = "travail_sol"

THEMES_ORDRE = (THEME_FROID, THEME_TUNNEL, THEME_IRRIGATION, THEME_TRAVAIL_SOL)
THEMES_LIBELLES = {
    THEME_FROID: "Froid",
    THEME_TUNNEL: "Tunnels",
    THEME_IRRIGATION: "Irrigation et stress thermique",
    THEME_TRAVAIL_SOL: "Travail du sol",
}


@dataclass(frozen=True)
class ParamAjustable:
    """Spec d'un seuil ajustable depuis l'UI (rendu en slider)."""

    label: str
    chemin: str
    min_value: float
    max_value: float
    step: float
    aide: str = ""


@dataclass(frozen=True)
class GuideDecision:
    """Guide de décision (actif ou inactif selon le signal)."""

    titre: str
    niveau: str
    picto: str
    detail_df: pd.DataFrame | None
    theme: str
    active: bool = True
    surlignage: dict[str, tuple[str, float]] = field(default_factory=dict)
    parametres_ajustables: list[ParamAjustable] = field(default_factory=list)


def load_exploitation(
    default_path: Path | str = DEFAULT_EXPLOITATION_PATH,
    local_override_path: Path | str | None = LOCAL_EXPLOITATION_OVERRIDE,
) -> dict[str, Any]:
    """Charge ``exploitation.yaml`` + override local éventuel."""
    config = load_yaml(default_path)
    if local_override_path is not None:
        p = Path(local_override_path)
        if p.exists():
            config = _deep_merge(config, load_yaml(p))
    return config


def get_chemin(d: dict, chemin: str) -> Any:
    """Lit une valeur dans un dict imbriqué via chemin dot."""
    cur: Any = d
    for p in chemin.split("."):
        cur = cur[p]
    return cur


def set_chemin(d: dict, chemin: str, val: Any) -> None:
    """Écrit une valeur dans un dict imbriqué via chemin dot."""
    parts = chemin.split(".")
    cur: Any = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = val


def _saison_active(exploitation: dict[str, Any], cle: str, mois_courant: int) -> bool:
    """True si le mois courant tombe dans la fenêtre `saisons[cle]`.

    Liste vide ou clé absente = fenêtre active toute l'année.
    """
    mois = exploitation.get("saisons", {}).get(cle)
    if not mois:
        return True
    return mois_courant in mois


def degres_jours_sous_seuil(t_min: pd.Series, seuil: float = 0.0) -> float:
    """Somme cumulée de l'écart sous ``seuil`` sur les jours t_min < seuil."""
    if t_min.empty:
        return 0.0
    sous = t_min[t_min < seuil]
    if sous.empty:
        return 0.0
    return float((seuil - sous).sum())


def plus_longue_suite_consecutive(masque: pd.Series) -> tuple[int, int, int] | None:
    """Plus longue suite de True consécutifs dans un masque booléen."""
    if masque.empty or not masque.any():
        return None
    best: tuple[int, int, int] | None = None
    cur_start: int | None = None
    cur_len = 0
    for i, v in enumerate(masque):
        if v:
            if cur_start is None:
                cur_start = i
            cur_len += 1
            if best is None or cur_len > best[2]:
                best = (cur_start, i, cur_len)
        else:
            cur_start = None
            cur_len = 0
    return best


def _fmt_date_courte(ts: pd.Timestamp) -> str:
    """Date courte ``lun. 02 juin``."""
    jours = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
    mois = [
        "janv.",
        "févr.",
        "mars",
        "avr.",
        "mai",
        "juin",
        "juil.",
        "août",
        "sept.",
        "oct.",
        "nov.",
        "déc.",
    ]
    return f"{jours[ts.weekday()]} {ts.day:02d} {mois[ts.month - 1]}"


# ---------- Paramètres ajustables réutilisables par règle ----------

_PARAMS_PURGE_GEL = [
    ParamAjustable(
        "Seuil T° min déclencheur (°C)",
        "seuils_gel.purge_irrigation_t_seuil_celsius",
        -5.0,
        5.0,
        0.5,
        "Sous cette T° min, on signale l'épisode (défaut 0 °C = gel franc).",
    ),
]

_PARAMS_VOILES = [
    ParamAjustable(
        "Seuil T° de comptage (°C)",
        "seuils_gel.voiles_p17_t_seuil_celsius",
        -10.0,
        5.0,
        0.5,
    ),
    ParamAjustable(
        "DJ cumulés déclencheurs",
        "seuils_gel.voiles_p17_degres_jours_min",
        0.5,
        30.0,
        0.5,
    ),
]

_PARAMS_RACINES = [
    ParamAjustable(
        "Seuil T° sévère (°C)",
        "seuils_gel.recolte_racines_t_seuil_celsius",
        -15.0,
        0.0,
        0.5,
    ),
    ParamAjustable(
        "DJ sévères déclencheurs",
        "seuils_gel.recolte_racines_degres_jours_min",
        1.0,
        30.0,
        0.5,
    ),
]

_PARAMS_AERATION = [
    ParamAjustable(
        "Seuil T° min nuit (°C)",
        "seuils_tunnel.aeration_nuit_t_min_celsius",
        5.0,
        20.0,
        0.5,
    ),
    ParamAjustable(
        "Nuits minimum",
        "seuils_tunnel.aeration_nuit_nuits_min",
        1.0,
        7.0,
        1.0,
    ),
]

_PARAMS_FERMETURE = [
    ParamAjustable(
        "Seuil T° min nuit (°C)",
        "seuils_tunnel.fermeture_nuit_t_min_celsius",
        -5.0,
        10.0,
        0.5,
    ),
    ParamAjustable(
        "Nuits minimum",
        "seuils_tunnel.fermeture_nuit_nuits_min",
        1.0,
        7.0,
        1.0,
    ),
]

_PARAMS_DEFICIT = [
    ParamAjustable(
        "Seuil bilan cumulé (mm)",
        "seuils_hydrique.deficit_mm",
        -50.0,
        0.0,
        1.0,
    ),
]

_PARAMS_STRESS = [
    ParamAjustable(
        "Seuil T° max (°C)",
        "seuils_thermique.stress_t_max_celsius",
        20.0,
        40.0,
        0.5,
    ),
    ParamAjustable(
        "Jours minimum",
        "seuils_thermique.stress_jours_min",
        1.0,
        7.0,
        1.0,
    ),
]

_PARAMS_FENETRE_SECHE = [
    ParamAjustable(
        "Seuil pluie « sèche » (mm/j)",
        "seuils_travail_sol.fenetre_seche_pluie_max_mm_par_jour",
        0.0,
        5.0,
        0.1,
    ),
    ParamAjustable(
        "Durée minimale (jours)",
        "seuils_travail_sol.fenetre_seche_duree_min_jours",
        1.0,
        7.0,
        1.0,
    ),
]

_PARAMS_FENETRE_PLUVIEUSE = [
    ParamAjustable(
        "Seuil pluie « pluvieuse » (mm/j)",
        "seuils_travail_sol.fenetre_pluvieuse_pluie_min_mm_par_jour",
        1.0,
        20.0,
        0.5,
    ),
    ParamAjustable(
        "Durée minimale (jours)",
        "seuils_travail_sol.fenetre_pluvieuse_duree_min_jours",
        1.0,
        7.0,
        1.0,
    ),
]


# ---------- Guides froid ----------


def regle_purge_irrigation_gel(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,  # noqa: ARG001
) -> GuideDecision | None:
    if "t_min_celsius" not in quotidien.columns or quotidien.empty:
        return None
    seuil_t = float(exploitation.get("seuils_gel", {}).get("purge_irrigation_t_seuil_celsius", 0.0))
    masque = quotidien["t_min_celsius"] <= seuil_t
    if masque.any():
        t_min_min = float(quotidien.loc[masque, "t_min_celsius"].min())
        titre = (
            f"Gel attendu sur 7 j — T° min prévue {t_min_min:.1f} °C (penser à purger l'irrigation)"
        )
        active = True
    else:
        t_min_observe = float(quotidien["t_min_celsius"].min())
        titre = (
            f"Pas de gel attendu — T° min mini +{t_min_observe:.1f} °C (seuil {seuil_t:+.1f} °C)"
        )
        active = False

    return GuideDecision(
        titre=titre,
        niveau=NIVEAU_ANTICIPER if active else NIVEAU_INFO,
        picto="❄️",
        detail_df=quotidien[["t_min_celsius"]],
        theme=THEME_FROID,
        active=active,
        surlignage={"t_min_celsius": ("≤", seuil_t)},
        parametres_ajustables=_PARAMS_PURGE_GEL,
    )


def regle_voiles_p17(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,  # noqa: ARG001
) -> GuideDecision | None:
    if not exploitation.get("equipement", {}).get("voiles_p17_disponibles", False):
        return None
    if "t_min_celsius" not in quotidien.columns or quotidien.empty:
        return None
    s = exploitation.get("seuils_gel", {})
    seuil_t = float(s.get("voiles_p17_t_seuil_celsius", 0.0))
    seuil_dj = float(s.get("voiles_p17_degres_jours_min", 2.0))

    dj = degres_jours_sous_seuil(quotidien["t_min_celsius"], seuil_t)
    if dj >= seuil_dj:
        titre = (
            f"Froid cumulé sur 7 j — {dj:.1f} DJ sous {seuil_t:.0f} °C (envisager des voiles P17)"
        )
        active = True
    else:
        titre = (
            f"Pas de froid cumulé notable — {dj:.1f} DJ sous {seuil_t:.0f} °C "
            f"(seuil {seuil_dj:.1f} DJ)"
        )
        active = False

    return GuideDecision(
        titre=titre,
        niveau=NIVEAU_ANTICIPER if active else NIVEAU_INFO,
        picto="🛡️",
        detail_df=quotidien[["t_min_celsius"]],
        theme=THEME_FROID,
        active=active,
        surlignage={"t_min_celsius": ("<", seuil_t)},
        parametres_ajustables=_PARAMS_VOILES,
    )


def regle_recolte_racines_avant_gel(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,
) -> GuideDecision | None:
    if not _saison_active(exploitation, "legumes_racine_au_champ", today.month):
        return None
    if "t_min_celsius" not in quotidien.columns or quotidien.empty:
        return None
    s = exploitation.get("seuils_gel", {})
    seuil_t = float(s.get("recolte_racines_t_seuil_celsius", -5.0))
    seuil_dj = float(s.get("recolte_racines_degres_jours_min", 4.0))

    dj = degres_jours_sous_seuil(quotidien["t_min_celsius"], seuil_t)
    if dj >= seuil_dj:
        titre = (
            f"Froid sévère cumulé sur 7 j — {dj:.1f} DJ sous {seuil_t:.0f} °C "
            "(envisager une récolte de protection)"
        )
        active = True
    else:
        titre = (
            f"Pas de froid sévère cumulé — {dj:.1f} DJ sous {seuil_t:.0f} °C "
            f"(seuil {seuil_dj:.1f} DJ)"
        )
        active = False

    return GuideDecision(
        titre=titre,
        niveau=NIVEAU_ANTICIPER if active else NIVEAU_INFO,
        picto="🥕",
        detail_df=quotidien[["t_min_celsius"]],
        theme=THEME_FROID,
        active=active,
        surlignage={"t_min_celsius": ("<", seuil_t)},
        parametres_ajustables=_PARAMS_RACINES,
    )


# ---------- Guides aération tunnels ----------


def regle_aeration_nuit_tunnels(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,
) -> GuideDecision | None:
    if not _saison_active(exploitation, "tunnels_en_culture", today.month):
        return None
    if "t_min_celsius" not in quotidien.columns or quotidien.empty:
        return None
    s = exploitation.get("seuils_tunnel", {})
    seuil_t = float(s.get("aeration_nuit_t_min_celsius", 12.0))
    nuits_min = int(s.get("aeration_nuit_nuits_min", 2))

    masque = quotidien["t_min_celsius"] >= seuil_t
    nb = int(masque.sum())
    if nb >= nuits_min:
        accord = "s" if nb > 1 else ""
        titre = (
            f"Nuits chaudes sur 7 j — {nb} nuit{accord} avec T° min ≥ "
            f"{seuil_t:.0f} °C (laisser les portes ouvertes la nuit)"
        )
        active = True
    else:
        t_min_max = float(quotidien["t_min_celsius"].max())
        titre = (
            f"Pas de nuits chaudes — T° min max {t_min_max:.1f} °C "
            f"(seuil {seuil_t:.0f} °C, {nb}/{nuits_min} nuits)"
        )
        active = False

    return GuideDecision(
        titre=titre,
        niveau=NIVEAU_INFO,
        picto="🌬️",
        detail_df=quotidien[["t_min_celsius"]],
        theme=THEME_TUNNEL,
        active=active,
        surlignage={"t_min_celsius": ("≥", seuil_t)},
        parametres_ajustables=_PARAMS_AERATION,
    )


def regle_fermeture_nuit_tunnels(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,
) -> GuideDecision | None:
    if not _saison_active(exploitation, "tunnels_en_culture", today.month):
        return None
    if "t_min_celsius" not in quotidien.columns or quotidien.empty:
        return None
    s = exploitation.get("seuils_tunnel", {})
    seuil_t = float(s.get("fermeture_nuit_t_min_celsius", 3.0))
    nuits_min = int(s.get("fermeture_nuit_nuits_min", 1))

    masque = quotidien["t_min_celsius"] <= seuil_t
    nb = int(masque.sum())
    if nb >= nuits_min:
        accord = "s" if nb > 1 else ""
        titre = (
            f"Nuits fraîches sur 7 j — {nb} nuit{accord} avec T° min ≤ "
            f"{seuil_t:.0f} °C (fermer les portes la nuit)"
        )
        active = True
    else:
        t_min_min = float(quotidien["t_min_celsius"].min())
        titre = f"Pas de nuits fraîches — T° min mini {t_min_min:+.1f} °C (seuil {seuil_t:.0f} °C)"
        active = False

    return GuideDecision(
        titre=titre,
        niveau=NIVEAU_INFO,
        picto="🔒",
        detail_df=quotidien[["t_min_celsius"]],
        theme=THEME_TUNNEL,
        active=active,
        surlignage={"t_min_celsius": ("≤", seuil_t)},
        parametres_ajustables=_PARAMS_FERMETURE,
    )


# ---------- Guides hydrique & thermique ----------


def regle_deficit_hydrique(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,  # noqa: ARG001
) -> GuideDecision | None:
    cols_requises = {"pluie_24h_mm", "etp_mm"}
    if not cols_requises.issubset(quotidien.columns) or quotidien.empty:
        return None
    seuil_mm = float(exploitation.get("seuils_hydrique", {}).get("deficit_mm", -10.0))
    bilan_cumul = float((quotidien["pluie_24h_mm"] - quotidien["etp_mm"]).sum())

    detail_df = quotidien[["pluie_24h_mm", "etp_mm"]].copy()
    detail_df["bilan_eau_jour_mm"] = detail_df["pluie_24h_mm"] - detail_df["etp_mm"]

    if bilan_cumul <= seuil_mm:
        titre = (
            f"Déficit hydrique sur 7 j — bilan pluie − ETP {bilan_cumul:+.1f} mm "
            "(vérifier humidité du sol, anticiper irrigation)"
        )
        active = True
    else:
        titre = (
            f"Bilan hydrique correct — {bilan_cumul:+.1f} mm sur 7 j "
            f"(seuil déficit {seuil_mm:+.1f} mm)"
        )
        active = False

    return GuideDecision(
        titre=titre,
        niveau=NIVEAU_ANTICIPER if active else NIVEAU_INFO,
        picto="💧",
        detail_df=detail_df,
        theme=THEME_IRRIGATION,
        active=active,
        surlignage={"bilan_eau_jour_mm": ("<", 0.0)},
        parametres_ajustables=_PARAMS_DEFICIT,
    )


def regle_stress_thermique(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,  # noqa: ARG001
) -> GuideDecision | None:
    """Fortes chaleurs prolongées → bassinage / ombrage (Agrobio 35)."""
    if "t_max_celsius" not in quotidien.columns or quotidien.empty:
        return None
    s = exploitation.get("seuils_thermique", {})
    seuil_t = float(s.get("stress_t_max_celsius", 28.0))
    jours_min = int(s.get("stress_jours_min", 2))

    masque = quotidien["t_max_celsius"] >= seuil_t
    nb = int(masque.sum())
    if nb >= jours_min:
        accord = "s" if nb > 1 else ""
        titre = (
            f"Fortes chaleurs sur 7 j — {nb} jour{accord} avec T° max ≥ "
            f"{seuil_t:.0f} °C (anticiper bassinage, ombrage, aération max)"
        )
        active = True
    else:
        t_max_max = float(quotidien["t_max_celsius"].max())
        titre = (
            f"Pas de fortes chaleurs — T° max max {t_max_max:.1f} °C "
            f"(seuil {seuil_t:.0f} °C, {nb}/{jours_min} jours)"
        )
        active = False

    return GuideDecision(
        titre=titre,
        niveau=NIVEAU_ANTICIPER if active else NIVEAU_INFO,
        picto="🌡️",
        detail_df=quotidien[["t_max_celsius"]],
        theme=THEME_IRRIGATION,
        active=active,
        surlignage={"t_max_celsius": ("≥", seuil_t)},
        parametres_ajustables=_PARAMS_STRESS,
    )


# ---------- Guides travail du sol ----------


def regle_fenetre_seche_travail_sol_hiver(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,
) -> GuideDecision | None:
    if not _saison_active(exploitation, "travail_sol_recherche_fenetre_seche", today.month):
        return None
    if "pluie_24h_mm" not in quotidien.columns or quotidien.empty:
        return None
    s = exploitation.get("seuils_travail_sol", {})
    seuil_pluie = float(s.get("fenetre_seche_pluie_max_mm_par_jour", 1.0))
    duree_min = int(s.get("fenetre_seche_duree_min_jours", 3))

    masque = quotidien["pluie_24h_mm"] <= seuil_pluie
    suite = plus_longue_suite_consecutive(masque)
    longueur = suite[2] if suite else 0
    if suite is not None and longueur >= duree_min:
        i_debut, i_fin, _ = suite
        debut = quotidien.index[i_debut]
        fin = quotidien.index[i_fin]
        titre = (
            f"Fenêtre sèche du {_fmt_date_courte(debut)} au {_fmt_date_courte(fin)} — "
            f"{longueur} jours sans pluie significative "
            "(envisager le travail du sol)"
        )
        active = True
    else:
        titre = (
            f"Pas de fenêtre sèche de {duree_min} jours — "
            f"plus longue suite {longueur} jour(s) "
            f"(seuil pluie ≤ {seuil_pluie:.1f} mm)"
        )
        active = False

    return GuideDecision(
        titre=titre,
        niveau=NIVEAU_INFO,
        picto="🚜",
        detail_df=quotidien[["pluie_24h_mm"]],
        theme=THEME_TRAVAIL_SOL,
        active=active,
        surlignage={"pluie_24h_mm": ("≤", seuil_pluie)},
        parametres_ajustables=_PARAMS_FENETRE_SECHE,
    )


def regle_fenetre_pluvieuse_travail_sol_ete(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,
) -> GuideDecision | None:
    if not _saison_active(exploitation, "travail_sol_recherche_fenetre_pluvieuse", today.month):
        return None
    if "pluie_24h_mm" not in quotidien.columns or quotidien.empty:
        return None
    s = exploitation.get("seuils_travail_sol", {})
    seuil_pluie = float(s.get("fenetre_pluvieuse_pluie_min_mm_par_jour", 5.0))
    duree_min = int(s.get("fenetre_pluvieuse_duree_min_jours", 2))

    masque = quotidien["pluie_24h_mm"] >= seuil_pluie
    suite = plus_longue_suite_consecutive(masque)
    longueur = suite[2] if suite else 0
    if suite is not None and longueur >= duree_min:
        i_debut, i_fin, _ = suite
        debut = quotidien.index[i_debut]
        fin = quotidien.index[i_fin]
        titre = (
            f"Fenêtre pluvieuse du {_fmt_date_courte(debut)} au {_fmt_date_courte(fin)} — "
            f"{longueur} jours de pluie attendue "
            "(anticiper le travail du sol)"
        )
        active = True
    else:
        titre = (
            f"Pas de fenêtre pluvieuse de {duree_min} jours — "
            f"plus longue suite {longueur} jour(s) "
            f"(seuil pluie ≥ {seuil_pluie:.1f} mm)"
        )
        active = False

    return GuideDecision(
        titre=titre,
        niveau=NIVEAU_ANTICIPER if active else NIVEAU_INFO,
        picto="🌧️",
        detail_df=quotidien[["pluie_24h_mm"]],
        theme=THEME_TRAVAIL_SOL,
        active=active,
        surlignage={"pluie_24h_mm": ("≥", seuil_pluie)},
        parametres_ajustables=_PARAMS_FENETRE_PLUVIEUSE,
    )


# ---------- Orchestration ----------


def evaluer_decisions(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,
) -> list[GuideDecision]:
    """Retourne tous les guides applicables (actifs ou inactifs).

    Les règles à fenêtre saisonnière (racines, fenêtre sèche, fenêtre
    pluvieuse, aération/fermeture tunnel hors saison de culture) sont
    filtrées : si non applicables, elles renvoient ``None`` et ne sont
    pas dans la liste. Les guides applicables sont tous inclus, avec
    leur drapeau ``active`` selon que le signal franchit son seuil.
    """
    guides: list[GuideDecision] = []

    for regle in (
        lambda q, t: regle_purge_irrigation_gel(q, exploitation, t),
        lambda q, t: regle_voiles_p17(q, exploitation, t),
        lambda q, t: regle_recolte_racines_avant_gel(q, exploitation, t),
        lambda q, t: regle_aeration_nuit_tunnels(q, exploitation, t),
        lambda q, t: regle_fermeture_nuit_tunnels(q, exploitation, t),
        lambda q, t: regle_deficit_hydrique(q, exploitation, t),
        lambda q, t: regle_stress_thermique(q, exploitation, t),
        lambda q, t: regle_fenetre_seche_travail_sol_hiver(q, exploitation, t),
        lambda q, t: regle_fenetre_pluvieuse_travail_sol_ete(q, exploitation, t),
    ):
        guide = regle(quotidien, today)
        if guide is not None:
            guides.append(guide)

    return guides


def grouper_par_theme(
    guides: list[GuideDecision],
) -> list[tuple[str, list[GuideDecision]]]:
    """Groupe les guides par thème dans l'ordre `THEMES_ORDRE`.

    Retourne une liste de paires (theme, libellé, guides). Les thèmes
    sans guide ne sont pas inclus. À l'intérieur d'un thème, l'ordre
    d'arrivée (= ordre `evaluer_decisions`) est conservé.
    """
    par_theme: dict[str, list[GuideDecision]] = {t: [] for t in THEMES_ORDRE}
    for g in guides:
        par_theme.setdefault(g.theme, []).append(g)
    return [(t, par_theme[t]) for t in THEMES_ORDRE if par_theme.get(t)]
