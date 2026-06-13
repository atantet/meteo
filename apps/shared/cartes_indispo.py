"""Motif lisible d'indisponibilité d'une carte (fetch image échoué).

Partagé par les fetchers de cartes (synoptiques Veille + ARPEGE-Europe géo) pour
afficher **explicitement** *pourquoi* une carte manque, au lieu de la faire
disparaître en silence (transparence : jamais d'absence muette anormale).
"""

from __future__ import annotations

import requests


def _motif_indispo(exc: Exception) -> str:
    """Raison lisible (FR) d'un échec de fetch image, pour l'afficher au lecteur."""
    if isinstance(exc, requests.HTTPError):
        statut = exc.response.status_code if exc.response is not None else None
        if statut == 404:
            return "non encore publiée"
        return f"erreur HTTP {statut}" if statut else "erreur HTTP"
    if isinstance(exc, requests.Timeout):
        return "délai dépassé"
    if isinstance(exc, requests.RequestException):
        return "erreur réseau"
    return "image illisible"
