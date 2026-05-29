"""Indicateurs pépinière — calendrier semis et durées d'élevage.

Périmètre v0 : calcul de la date de semis recommandée à partir d'une
date de plantation cible et de la durée d'élevage de la culture.

Cf. ADR-0009 pour le cadrage complet, les choix de périmètre et les
limites assumées.

Référence :

> ``date_semis = date_plantation_cible − durée_élevage − marge_sécurité``

La date de plantation cible est typiquement déterminée par la climato
(90ᵉ percentile du dernier gel printanier pour les cultures sensibles
au gel, ou un seuil saisonnier libre pour les autres).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

# Catalogue durées d'élevage par culture, packagé avec le module.
FILEPATH_CYCLES: Path = Path(__file__).parent / "pepiniere_cycles.json"

with open(FILEPATH_CYCLES) as f:
    CYCLES: dict[str, dict] = json.load(f)


def cultures_disponibles() -> list[str]:
    """Liste des cultures référencées (hors métadonnées)."""
    return [k for k in CYCLES if not k.startswith("_")]


def duree_elevage_jours(culture: str) -> int:
    """Durée d'élevage en pépinière (semis → plant repiquable), en jours.

    Returns ``0`` pour les cultures en semis direct (carotte, etc.).
    """
    if culture not in CYCLES:
        raise KeyError(
            f"Culture inconnue : {culture!r}. Disponibles : {sorted(cultures_disponibles())}"
        )
    return int(CYCLES[culture]["duree_elevage_j"])


def est_sensible_gel(culture: str) -> bool:
    """True si la culture est sensible au gel au stade plant repiquable."""
    if culture not in CYCLES:
        raise KeyError(f"Culture inconnue : {culture!r}.")
    return bool(CYCLES[culture].get("sensible_gel", False))


def date_semis_recommandee(
    culture: str,
    date_plantation_cible: date,
    marge_securite_j: int = 7,
) -> date:
    """Calcule la date de semis recommandée pour atteindre la cible.

    Parameters
    ----------
    culture :
        Nom de culture parmi ``cultures_disponibles()``.
    date_plantation_cible :
        Date à laquelle on souhaite repiquer en pleine terre.
    marge_securite_j :
        Marge supplémentaire pour absorber les retards d'élevage
        (météo défavorable, germination lente). Défaut 7 jours.

    Returns
    -------
    date
        Date de semis recommandée. Pour les cultures en semis direct
        (durée = 0), renvoie ``date_plantation_cible``.
    """
    duree = duree_elevage_jours(culture)
    if duree == 0:
        return date_plantation_cible
    return date_plantation_cible - timedelta(days=duree + marge_securite_j)


def calendrier_semis(
    date_plantation_cible: date,
    cultures: list[str] | None = None,
    marge_securite_j: int = 7,
) -> list[dict]:
    """Génère un calendrier semis pour une date de plantation cible donnée.

    Parameters
    ----------
    date_plantation_cible :
        Date cible commune pour toutes les cultures listées.
    cultures :
        Liste de cultures. Si None, prend toutes les cultures
        sensibles au gel (pour lesquelles la cible "après gel" a du
        sens).
    marge_securite_j :
        Marge d'élevage.

    Returns
    -------
    list[dict]
        Une entrée par culture avec :
        - ``culture`` (str)
        - ``date_semis`` (date)
        - ``date_plantation`` (date) = cible
        - ``duree_elevage_j`` (int)
        - ``sensible_gel`` (bool)
    """
    if cultures is None:
        cultures = [c for c in cultures_disponibles() if est_sensible_gel(c)]

    sortie: list[dict] = []
    for culture in sorted(cultures):
        sortie.append(
            {
                "culture": culture,
                "date_semis": date_semis_recommandee(
                    culture, date_plantation_cible, marge_securite_j
                ),
                "date_plantation": date_plantation_cible,
                "duree_elevage_j": duree_elevage_jours(culture),
                "sensible_gel": est_sensible_gel(culture),
            }
        )
    return sortie
