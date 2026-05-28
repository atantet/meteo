"""Évaluation des alertes pour l'App 1 Veille.

À partir des indicateurs calculés (cf. ``indicateurs.py``) et des
seuils de la config, identifie les alertes déclenchées : gel, canicule,
pluie intense, vent fort.

Le ton des messages reste **informationnel** (cf. principe n°1 — ne pas
prescrire d'action, exposer le signal). Chaque alerte porte sa source
de seuil pour traçabilité (principe n°5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .indicateurs import IndicateursVeille


@dataclass
class Alerte:
    """Une alerte déclenchée par un seuil franchi."""

    type: str  # gel | canicule | pluie_intense | vent_fort
    niveau: str  # warning | critique
    titre: str  # texte court ("Gel attendu cette nuit")
    valeur: float  # valeur observée/prévue
    unite: str  # unité d'affichage
    seuil: float  # seuil configuré ayant déclenché


def evaluer_alertes(ind: IndicateursVeille, config: dict[str, Any]) -> list[Alerte]:
    """Évalue les 4 types d'alertes à partir des indicateurs et de la config.

    Parameters
    ----------
    ind :
        Indicateurs calculés pour les prochaines 24-168 h.
    config :
        Configuration Veille (cf. ``config.load_config``). Lit la
        section ``alertes`` pour les seuils et le drapeau ``actif``.

    Returns
    -------
    list[Alerte]
        Liste des alertes effectivement déclenchées, ordre fixe
        (gel, canicule, pluie, vent). Liste vide si aucune.
    """
    cfg = config["alertes"]
    alertes: list[Alerte] = []

    g = cfg["gel"]
    if g["actif"] and ind.temperature_min_24h_celsius < g["seuil_celsius"]:
        alertes.append(
            Alerte(
                type="gel",
                niveau="critique",
                titre=(f"Gel attendu — T° min prévue {ind.temperature_min_24h_celsius:.1f} °C"),
                valeur=ind.temperature_min_24h_celsius,
                unite="°C",
                seuil=g["seuil_celsius"],
            )
        )

    c = cfg["canicule"]
    if c["actif"] and ind.temperature_max_24h_celsius > c["seuil_celsius"]:
        alertes.append(
            Alerte(
                type="canicule",
                niveau="critique",
                titre=(f"Canicule — T° max prévue {ind.temperature_max_24h_celsius:.1f} °C"),
                valeur=ind.temperature_max_24h_celsius,
                unite="°C",
                seuil=c["seuil_celsius"],
            )
        )

    p = cfg["pluie_intense"]
    if p["actif"] and ind.cumul_pluie_24h_mm > p["seuil_mm_24h"]:
        alertes.append(
            Alerte(
                type="pluie_intense",
                niveau="warning",
                titre=(f"Pluie intense — cumul 24 h prévu {ind.cumul_pluie_24h_mm:.1f} mm"),
                valeur=ind.cumul_pluie_24h_mm,
                unite="mm/24h",
                seuil=p["seuil_mm_24h"],
            )
        )

    v = cfg["vent_fort"]
    # On utilise les rafales pour l'alerte, plus représentatives du
    # risque opérationnel (bâches volantes) que le vent moyen.
    if v["actif"] and ind.rafales_max_24h_kmh > v["seuil_kmh"]:
        alertes.append(
            Alerte(
                type="vent_fort",
                niveau="warning",
                titre=(f"Vent fort — rafales prévues {ind.rafales_max_24h_kmh:.0f} km/h"),
                valeur=ind.rafales_max_24h_kmh,
                unite="km/h",
                seuil=v["seuil_kmh"],
            )
        )

    return alertes


def resume_alertes(alertes: list[Alerte]) -> str:
    """Texte court pour sujet d'email : ex. "gel + vent fort" ou "RAS"."""
    if not alertes:
        return "RAS"
    return " + ".join(a.type.replace("_", " ") for a in alertes)
