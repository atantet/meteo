"""Évaluation des alertes pour l'App 1 Veille.

À partir des indicateurs calculés (cf. ``indicateurs.py``) et des
seuils de la config, identifie les alertes déclenchées :
gel (purge irrigation + voilage), canicule, pluie intense, vent fort,
risque maladies (nuit douce).

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

    type: str  # gel | canicule_* | pluie_intense | vent_fort | risque_maladies
    niveau: str  # warning | critique
    titre: str  # texte court ("Gel attendu cette nuit")
    valeur: float  # valeur observée/prévue
    unite: str  # unité d'affichage
    seuil: float  # seuil configuré ayant déclenché


def evaluer_alertes(ind: IndicateursVeille, config: dict[str, Any]) -> list[Alerte]:
    """Évalue les alertes à partir des indicateurs et de la config.

    Parameters
    ----------
    ind :
        Indicateurs calculés pour les prochaines 24-48 h.
    config :
        Configuration Veille (cf. ``config.load_config``). Lit la
        section ``alertes`` pour les seuils et le drapeau ``actif``.

    Returns
    -------
    list[Alerte]
        Liste des alertes effectivement déclenchées, ordre fixe
        (gel, canicule aération, canicule stress, risque maladies,
        pluie, vent). Liste vide si aucune.
    """
    cfg = config["alertes"]
    alertes: list[Alerte] = []

    # Gel : T° min ≤ seuil sur une plage de 6 h des 0-48 h (les 4 plages
    # pavant la journée, c'est équivalent au min sur 48 h). Couvre les
    # deux actions terrain : purge du réseau d'irrigation ET voilage des
    # cultures sensibles (P17). Warning, anticipation.
    g = cfg.get("gel", {"actif": False})
    if g["actif"] and ind.temperature_min_48h_celsius <= g["seuil_celsius"]:
        alertes.append(
            Alerte(
                type="gel",
                niveau="warning",
                titre=(
                    f"Risque de gel sous 48 h — T° min prévue "
                    f"{ind.temperature_min_48h_celsius:.1f} °C "
                    "(purger l'irrigation et voiler les cultures sensibles)"
                ),
                valeur=ind.temperature_min_48h_celsius,
                unite="°C",
                seuil=g["seuil_celsius"],
            )
        )

    # Canicule aération : T° max 0-48 h ≥ seuil (palier où sous abri ça
    # surchauffe). Warning, anticipation aération max dès le matin.
    ca = cfg.get("canicule_aeration", {"actif": False})
    if ca["actif"] and ind.temperature_max_48h_celsius >= ca["seuil_celsius"]:
        alertes.append(
            Alerte(
                type="canicule_aeration",
                niveau="warning",
                titre=(
                    f"Chaleur sous 48 h — T° max prévue "
                    f"{ind.temperature_max_48h_celsius:.1f} °C "
                    "(aérer au max les tunnels dès le matin)"
                ),
                valeur=ind.temperature_max_48h_celsius,
                unite="°C",
                seuil=ca["seuil_celsius"],
            )
        )

    # Canicule stress : T° max 0-24 h ≥ seuil (stress thermique
    # cultures). Critique, bassinages midi + ombrage + travail tôt.
    cs = cfg.get("canicule_stress", {"actif": False})
    if cs["actif"] and ind.temperature_max_24h_celsius >= cs["seuil_celsius"]:
        alertes.append(
            Alerte(
                type="canicule_stress",
                niveau="critique",
                titre=(
                    f"Stress thermique — T° max prévue "
                    f"{ind.temperature_max_24h_celsius:.1f} °C "
                    "(bassinages midi 3-4 min, ombrage, travail avant 10 h)"
                ),
                valeur=ind.temperature_max_24h_celsius,
                unite="°C",
                seuil=cs["seuil_celsius"],
            )
        )

    # Risque maladies générique : nuit douce (T° min de la nuit à venir
    # ≥ seuil) → conditions propices au développement de maladies sous
    # abri mal aéré. PAS un modèle pathogène, juste un constat météo.
    # Condition unique sur la température nocturne (l'humidité n'est plus
    # un critère ; le mildiou tomate garde son propre critère via Smith).
    rm = cfg.get("risque_maladies", {"actif": False})
    if rm["actif"] and ind.temperature_min_nuit_prochaine_celsius >= rm["t_min_nuit_celsius"]:
        alertes.append(
            Alerte(
                type="risque_maladies",
                niveau="warning",
                titre=(
                    f"Conditions propices aux maladies — "
                    f"T° min nuit {ind.temperature_min_nuit_prochaine_celsius:.1f} °C "
                    "(maintenir ouvrants la nuit)"
                ),
                valeur=ind.temperature_min_nuit_prochaine_celsius,
                unite="°C",
                seuil=rm["t_min_nuit_celsius"],
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
