"""Helpers de présentation (libellés, format, couleurs) — App 2 UI.

Séparés de ``streamlit_app.py`` pour rester testables sans rendre la
UI Streamlit.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Libellés humains des colonnes pour l'affichage.
LIBELLES_COLONNES: dict[str, str] = {
    "t_min_celsius": "T° min (°C)",
    "t_max_celsius": "T° max (°C)",
    "t_moy_celsius": "T° moy (°C)",
    "t_moy_normale_celsius": "Normale T° (°C)",
    "ecart_normale_celsius": "Écart normale (°C)",
    "pluie_24h_mm": "Pluie 24 h (mm)",
    "rafales_max_kmh": "Rafales (km/h)",
    "direction_vent_cardinal": "Vent dom.",
    "etp_mm": "ETP (mm)",
    "bilan_eau_cumul_mm": "Bilan eau cumulé (mm)",
}

# Précision d'affichage par colonne.
PRECISION: dict[str, int] = {
    "t_min_celsius": 1,
    "t_max_celsius": 1,
    "t_moy_celsius": 1,
    "t_moy_normale_celsius": 1,
    "ecart_normale_celsius": 1,
    "pluie_24h_mm": 1,
    "rafales_max_kmh": 0,
    "etp_mm": 1,
    "bilan_eau_cumul_mm": 1,
}

# Couleurs (alignées sur App 1 Veille pour la cohérence visuelle).
COULEUR_CRITIQUE: str = "#fcdad7"  # pastel rouge
COULEUR_WARNING: str = "#fce5cf"  # pastel orange
COULEUR_INFO: str = "#d4e6f1"  # pastel bleu (pluie)


def libelle(colonne: str) -> str:
    """Libellé humain pour une colonne."""
    return LIBELLES_COLONNES.get(colonne, colonne)


def formater_index_date(df: pd.DataFrame, tz: str = "Europe/Paris") -> pd.DataFrame:
    """Renomme l'index pour affichage : ``Lun 15 juin``."""
    out = df.copy()
    out.index = pd.Series(out.index).dt.strftime("%a %d %b").tolist()
    out.index.name = "Date"
    return out


def styler_ligne(row: pd.Series, alertes_cfg: dict[str, Any]) -> list[str]:
    """Retourne la liste des styles CSS par cellule selon les seuils.

    Une cellule est colorée si la valeur franchit le seuil d'alerte
    correspondant et que l'alerte est active dans la config.
    """
    styles = [""] * len(row)
    cols = list(row.index)

    gel = alertes_cfg.get("gel", {})
    if gel.get("actif") and "T° min (°C)" in cols and row["T° min (°C)"] < gel["seuil_celsius"]:
        styles[cols.index("T° min (°C)")] = f"background-color: {COULEUR_CRITIQUE}"

    canicule = alertes_cfg.get("canicule", {})
    if (
        canicule.get("actif")
        and "T° max (°C)" in cols
        and row["T° max (°C)"] > canicule["seuil_celsius"]
    ):
        styles[cols.index("T° max (°C)")] = f"background-color: {COULEUR_CRITIQUE}"

    pluie = alertes_cfg.get("pluie_intense", {})
    if (
        pluie.get("actif")
        and "Pluie 24 h (mm)" in cols
        and row["Pluie 24 h (mm)"] > pluie["seuil_mm_24h"]
    ):
        styles[cols.index("Pluie 24 h (mm)")] = f"background-color: {COULEUR_INFO}"

    vent = alertes_cfg.get("vent_fort", {})
    if vent.get("actif") and "Rafales (km/h)" in cols and row["Rafales (km/h)"] > vent["seuil_kmh"]:
        styles[cols.index("Rafales (km/h)")] = f"background-color: {COULEUR_WARNING}"

    return styles


def preparer_table_affichage(quotidien: pd.DataFrame, tz: str = "Europe/Paris") -> pd.DataFrame:
    """Renomme colonnes + arrondit selon PRECISION + reformate index.

    Si ``direction_vent_cardinal`` et ``direction_vent_deg`` sont présents,
    affiche ``NO (315°)`` dans la colonne renommée.
    """
    out = quotidien.copy()
    # Compose direction "NO (315°)" si les 2 colonnes sont présentes.
    if "direction_vent_cardinal" in out.columns and "direction_vent_deg" in out.columns:
        out["direction_vent_cardinal"] = out.apply(
            lambda r: (
                f"{r['direction_vent_cardinal']} ({r['direction_vent_deg']:.0f}°)"
                if isinstance(r["direction_vent_cardinal"], str) and r["direction_vent_cardinal"]
                else ""
            ),
            axis=1,
        )
        # On masque la colonne degrés brute après composition.
        out = out.drop(columns=["direction_vent_deg"])
    for col, prec in PRECISION.items():
        if col in out.columns:
            out[col] = out[col].round(prec)
    out = out.rename(columns=LIBELLES_COLONNES)
    return formater_index_date(out, tz=tz)
