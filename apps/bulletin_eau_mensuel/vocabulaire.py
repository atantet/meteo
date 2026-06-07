"""Mapping classes → couleurs pour le bulletin eau (palette Wong partagée)."""

from __future__ import annotations

from apps.shared.style import (
    COULEUR_CHAUD,
    COULEUR_NEUTRE,
    COULEUR_OK,
    COULEUR_WARNING,
)

# Niveau « crise » VigiEau — plus sévère que le vermillon des alertes.
COULEUR_CRISE = "#7d0000"


def couleur_classe_nappe(classe: str) -> str:
    """`bas` (tension) → vermillon, `haut` → vert, `normal` → gris."""
    if classe == "bas":
        return COULEUR_CHAUD
    if classe == "haut":
        return COULEUR_OK
    return COULEUR_NEUTRE


def couleur_niveau_restriction(niveau: str) -> str:
    """Couleur croissante avec la sévérité de la restriction."""
    return {
        "aucune": COULEUR_OK,
        "vigilance": COULEUR_WARNING,
        "alerte": COULEUR_CHAUD,
        "alerte_renforcee": COULEUR_CHAUD,
        "crise": COULEUR_CRISE,
    }.get(niveau, COULEUR_NEUTRE)
