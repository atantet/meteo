"""Cartes d'invitation pour l'App 2 Opérationnelle.

À partir d'un DataFrame ``quotidien`` (sortie
``calculer_indicateurs_quotidiens``) et d'une config exploitation, produit
une liste de ``Carte`` qui suggèrent à l'utilisateur des vérifications
terrain motivées par la météo prévue à 7 j.

Philosophie : on **invite** l'utilisateur à vérifier empiriquement, on ne
**tranche** pas. Chaque carte suit le pattern hérité de l'App 1 Veille
pour le titre : ``<Signal court> — <valeur unité> (<action courte>)``.

Structure d'une carte :
- ``titre`` : signal + valeur + parenthèse action courte (style App 1)
- ``invitation`` : rattachement métier court (sous-titre lead)
- ``niveau`` : info | anticiper | critique (mapping couleur Wong)
- ``picto`` : emoji court
- ``detail_intro`` : commentaire markdown court, **uniquement** si ajoute
  une info absente du titre/invitation. Vide sinon.
- ``detail_df`` : **tous les jours** de la fenêtre 7 j (pas seulement
  ceux qui déclenchent) — la mise en évidence visuelle des jours
  déclencheurs se fait via ``surlignage``.
- ``detail_source`` : footer court ajusté aux indicateurs réellement
  utilisés par la carte (T° seule, ETP, pluie+ETP…).
- ``surlignage`` : ``{colonne: (op, seuil)}`` pour marquer dans le
  tableau les valeurs qui dépassent le seuil. ``op ∈ {"≤","<","≥",">"}``.
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

# Sources spécifiques par type d'indicateur utilisé. Plus précis que le
# footer générique : on n'annonce pas FAO 56 quand la carte n'utilise
# que la T° min, par exemple.
SOURCE_T_FORECAST = "Source : Open-Meteo · forecast best_match · T° agrégée par jour local."
SOURCE_ETP_SOCLE = (
    "Source : ETP socle FAO 56 Penman-Monteith horaire, calculée à "
    "partir d'Open-Meteo (T°, HR, vent, rayonnement)."
)
SOURCE_PLUIE_ETP = (
    "Source : Open-Meteo · forecast best_match (pluie) + ETP socle FAO 56 Penman-Monteith horaire."
)


@dataclass(frozen=True)
class Carte:
    """Invitation à vérifier empiriquement, motivée par un signal météo."""

    titre: str
    invitation: str
    niveau: str
    picto: str
    detail_df: pd.DataFrame | None
    detail_source: str
    detail_intro: str = ""
    surlignage: dict[str, tuple[str, float]] = field(default_factory=dict)


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


def _saison_active(exploitation: dict[str, Any], cle: str, mois_courant: int) -> bool:
    """True si le mois courant tombe dans la fenêtre `saisons[cle]`.

    Liste vide ou clé absente = fenêtre active toute l'année.
    """
    mois = exploitation.get("saisons", {}).get(cle)
    if not mois:  # None, [], absent → toujours actif
        return True
    return mois_courant in mois


def degres_jours_negatifs(t_min: pd.Series) -> float:
    """Somme des |T° min| pour les jours où T° min < 0, sur la fenêtre.

    Mesure intégrée du froid attendu : 1 nuit à -3 °C ≡ 3 nuits à -1 °C
    ≡ 3 degrés-jours négatifs. Plus discriminant qu'un seuil ponctuel.
    """
    if t_min.empty:
        return 0.0
    sous_zero = t_min[t_min < 0]
    if sous_zero.empty:
        return 0.0
    return float(-sous_zero.sum())


# ---------- Cartes gel ----------


def regle_purge_irrigation_gel(
    quotidien: pd.DataFrame,
    today: pd.Timestamp,  # noqa: ARG001
) -> Carte | None:
    """Gel attendu → invitation à purger l'irrigation extérieure.

    Active toute l'année : dès qu'on annonce du gel, le rappel est utile
    pour toute installation d'irrigation encore en eau.
    """
    if "t_min_celsius" not in quotidien.columns or quotidien.empty:
        return None
    masque = quotidien["t_min_celsius"] <= 0.0
    if not masque.any():
        return None
    t_min_min = float(quotidien.loc[masque, "t_min_celsius"].min())

    return Carte(
        titre=(
            f"Gel attendu sur 7 j — T° min prévue {t_min_min:.1f} °C (penser à purger l'irrigation)"
        ),
        invitation="Pour toute irrigation extérieure encore en eau.",
        niveau=NIVEAU_ANTICIPER,
        picto="❄️",
        detail_df=quotidien[["t_min_celsius"]],
        detail_source=SOURCE_T_FORECAST,
        surlignage={"t_min_celsius": ("≤", 0.0)},
    )


def regle_voiles_p17(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,  # noqa: ARG001
) -> Carte | None:
    """Froid cumulé (degrés-jours négatifs) → invitation aux voiles P17."""
    if not exploitation.get("equipement", {}).get("voiles_p17_disponibles", False):
        return None
    if "t_min_celsius" not in quotidien.columns or quotidien.empty:
        return None
    seuil_dj = float(exploitation.get("seuils_gel", {}).get("voiles_p17_degres_jours_neg_min", 2.0))
    dj_neg = degres_jours_negatifs(quotidien["t_min_celsius"])
    if dj_neg < seuil_dj:
        return None

    return Carte(
        titre=(
            f"Froid cumulé sur 7 j — {dj_neg:.1f} degrés-jours négatifs (envisager des voiles P17)"
        ),
        invitation="Pour les cultures sensibles au gel.",
        niveau=NIVEAU_ANTICIPER,
        picto="🛡️",
        detail_intro=(
            "Un *degré-jour négatif* = somme cumulée des |T° min| sur les "
            f"jours où la T° min est sous 0 °C (seuil paramétré : {seuil_dj:.1f} DJ)."
        ),
        detail_df=quotidien[["t_min_celsius"]],
        detail_source=SOURCE_T_FORECAST,
        surlignage={"t_min_celsius": ("<", 0.0)},
    )


def regle_recolte_racines_avant_gel(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,
) -> Carte | None:
    """Froid cumulé sévère + racines en saison → invitation récolte."""
    if not _saison_active(exploitation, "legumes_racine_au_champ", today.month):
        return None
    if "t_min_celsius" not in quotidien.columns or quotidien.empty:
        return None
    seuil_dj = float(
        exploitation.get("seuils_gel", {}).get("recolte_racines_degres_jours_neg_min", 8.0)
    )
    dj_neg = degres_jours_negatifs(quotidien["t_min_celsius"])
    if dj_neg < seuil_dj:
        return None

    return Carte(
        titre=(
            f"Froid sévère cumulé sur 7 j — {dj_neg:.1f} degrés-jours négatifs "
            "(envisager une récolte de protection)"
        ),
        invitation="Pour les légumes racine encore au champ (conservation).",
        niveau=NIVEAU_ANTICIPER,
        picto="🥕",
        detail_df=quotidien[["t_min_celsius"]],
        detail_source=SOURCE_T_FORECAST,
        surlignage={"t_min_celsius": ("<", 0.0)},
    )


# ---------- Cartes aération tunnels ----------


def regle_aeration_nuit_tunnels(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,
) -> Carte | None:
    """Nuits chaudes → invitation à aérer les tunnels la nuit."""
    if not _saison_active(exploitation, "tunnels_en_culture", today.month):
        return None
    if "t_min_celsius" not in quotidien.columns or quotidien.empty:
        return None
    s = exploitation.get("seuils_tunnel", {})
    seuil_t = float(s.get("aeration_nuit_t_min_celsius", 12.0))
    nuits_min = int(s.get("aeration_nuit_nuits_min", 2))

    masque = quotidien["t_min_celsius"] >= seuil_t
    if int(masque.sum()) < nuits_min:
        return None
    nb = int(masque.sum())
    accord = "s" if nb > 1 else ""

    return Carte(
        titre=(
            f"Nuits chaudes sur 7 j — {nb} nuit{accord} avec T° min ≥ "
            f"{seuil_t:.0f} °C (laisser les portes ouvertes la nuit)"
        ),
        invitation="Pour limiter condensation et risque de maladies sous abri.",
        niveau=NIVEAU_INFO,
        picto="🌬️",
        detail_df=quotidien[["t_min_celsius"]],
        detail_source=SOURCE_T_FORECAST,
        surlignage={"t_min_celsius": ("≥", seuil_t)},
    )


def regle_fermeture_nuit_tunnels(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,
) -> Carte | None:
    """Nuits froides → invitation à fermer les tunnels la nuit."""
    if not _saison_active(exploitation, "tunnels_en_culture", today.month):
        return None
    if "t_min_celsius" not in quotidien.columns or quotidien.empty:
        return None
    s = exploitation.get("seuils_tunnel", {})
    seuil_t = float(s.get("fermeture_nuit_t_min_celsius", 3.0))
    nuits_min = int(s.get("fermeture_nuit_nuits_min", 1))

    masque = quotidien["t_min_celsius"] <= seuil_t
    if int(masque.sum()) < nuits_min:
        return None
    nb = int(masque.sum())
    accord = "s" if nb > 1 else ""

    return Carte(
        titre=(
            f"Nuits fraîches sur 7 j — {nb} nuit{accord} avec T° min ≤ "
            f"{seuil_t:.0f} °C (fermer les portes la nuit)"
        ),
        invitation="Pour préserver les cultures sensibles sous abri.",
        niveau=NIVEAU_INFO,
        picto="🔒",
        detail_df=quotidien[["t_min_celsius"]],
        detail_source=SOURCE_T_FORECAST,
        surlignage={"t_min_celsius": ("≤", seuil_t)},
    )


# ---------- Cartes bilan hydrique (v1) ----------


def regle_deficit_plein_champ(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,  # noqa: ARG001
) -> Carte | None:
    """Bilan eau cumulé négatif → invitation à vérifier l'humidité du sol."""
    cols_requises = {"pluie_24h_mm", "etp_mm"}
    if not cols_requises.issubset(quotidien.columns) or quotidien.empty:
        return None
    seuil_mm = float(exploitation.get("seuils_hydrique", {}).get("deficit_plein_champ_mm", -10.0))
    bilan_cumul = float((quotidien["pluie_24h_mm"] - quotidien["etp_mm"]).sum())
    if bilan_cumul > seuil_mm:
        return None

    detail_df = quotidien[["pluie_24h_mm", "etp_mm"]].copy()
    detail_df["bilan_eau_jour_mm"] = detail_df["pluie_24h_mm"] - detail_df["etp_mm"]

    return Carte(
        titre=(
            f"Déficit hydrique sur 7 j — bilan pluie − ETP {bilan_cumul:+.1f} mm "
            "(vérifier humidité du sol, anticiper irrigation)"
        ),
        invitation="Pour la reprise en plein champ et le remplissage du bassin.",
        niveau=NIVEAU_ANTICIPER,
        picto="💧",
        detail_intro=(
            "Indicateur brut sans réserve utile du sol. Pour le bilan "
            "complet avec RU, voir « Bilan hydrique — modèle sol complet » "
            "plus bas."
        ),
        detail_df=detail_df,
        detail_source=SOURCE_PLUIE_ETP,
        surlignage={"bilan_eau_jour_mm": ("<", 0.0)},
    )


def regle_demande_evap_tunnel(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,
) -> Carte | None:
    """ETP cumulée 7 j élevée → invitation à anticiper l'irrigation tunnel."""
    if not _saison_active(exploitation, "tunnels_en_culture", today.month):
        return None
    if "etp_mm" not in quotidien.columns or quotidien.empty:
        return None
    seuil_mm = float(
        exploitation.get("seuils_hydrique", {}).get("demande_evap_tunnel_etp_cumul_mm", 20.0)
    )
    etp_cumul = float(quotidien["etp_mm"].sum())
    if etp_cumul < seuil_mm:
        return None
    etp_moy = etp_cumul / max(1, len(quotidien))
    # Surligne les jours où l'ETP est au-dessus de la moyenne hebdo —
    # repère les pics de demande dans la semaine.
    seuil_surlignage = etp_moy

    return Carte(
        titre=(
            f"Forte demande évaporative sur 7 j — ETP {etp_cumul:.0f} mm cumulés "
            "(anticiper irrigation et bassinage tunnel)"
        ),
        invitation="Pour les cultures sous tunnel (vérifier le stock d'eau).",
        niveau=NIVEAU_ANTICIPER,
        picto="🌡️",
        detail_intro=(
            "ETP **extérieure** : multiplier par *k_tunnel* "
            "(~0.55 à 0.90 selon ventilation) pour estimer la demande "
            "réelle sous abri."
        ),
        detail_df=quotidien[["etp_mm"]],
        detail_source=SOURCE_ETP_SOCLE,
        surlignage={"etp_mm": (">", seuil_surlignage)},
    )


# ---------- Orchestration ----------


def evaluer_decisions(
    quotidien: pd.DataFrame,
    exploitation: dict[str, Any],
    today: pd.Timestamp,
) -> list[Carte]:
    """Évalue toutes les règles et retourne les cartes actives.

    Parameters
    ----------
    quotidien :
        Sortie de ``calculer_indicateurs_quotidiens`` (DataFrame indexé
        par date locale, colonnes t_min/t_max/pluie/etp/etc.).
    exploitation :
        Dict chargé depuis ``config/exploitation.yaml``.
    today :
        Timestamp tz-naive représentant la date locale courante (utilisée
        pour les fenêtres saisonnières).
    """
    cartes: list[Carte] = []

    for regle in (
        regle_purge_irrigation_gel,
        lambda q, t: regle_voiles_p17(q, exploitation, t),
        lambda q, t: regle_recolte_racines_avant_gel(q, exploitation, t),
        lambda q, t: regle_aeration_nuit_tunnels(q, exploitation, t),
        lambda q, t: regle_fermeture_nuit_tunnels(q, exploitation, t),
        lambda q, t: regle_deficit_plein_champ(q, exploitation, t),
        lambda q, t: regle_demande_evap_tunnel(q, exploitation, t),
    ):
        carte = regle(quotidien, today)
        if carte is not None:
            cartes.append(carte)

    return cartes
