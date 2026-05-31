"""Quotidiens synthétiques pour la page démo de l'App 2 Opérationnelle.

Données fabriquées pour déclencher l'ensemble des cartes de décisions.
Hiver et été doivent être deux scénarios distincts : les saisons des
règles (racines, fenêtre sèche/pluvieuse) sont mutuellement exclusives.

Couverture attendue :

- ``quotidien_hiver()`` (15 janvier) : purge gel, voiles P17, récolte
  racines, fermeture nuit tunnel, fenêtre sèche.
- ``quotidien_ete()`` (15 juillet) : aération nuit tunnel, déficit plein
  champ, demande évap tunnel, fenêtre pluvieuse.

Utilisé par ``apps/operationnelle/streamlit_app_demo.py``.
"""

from __future__ import annotations

import pandas as pd


def quotidien_hiver() -> pd.DataFrame:
    """Scénario hiver — 7 jours synthétiques.

    - 5 nuits de gel (-8 à 0 °C) → purge + voiles + racines + fermeture
    - 4 jours secs consécutifs (pluie ≤ 1 mm) puis pluie → fenêtre sèche
    - ETP très basse (climat hivernal) → pas de demande évap
    - Bilan pluie − ETP positif (pluie en fin de fenêtre) → pas déficit
    """
    idx = pd.date_range("2026-01-15", periods=7, freq="D")
    return pd.DataFrame(
        {
            "t_min_celsius": [-5.0, -7.0, -8.0, -4.0, 0.0, 2.0, 5.0],
            "t_max_celsius": [2.0, 1.0, 0.0, 5.0, 8.0, 10.0, 12.0],
            "t_moy_celsius": [-1.5, -3.0, -4.0, -0.5, 4.0, 6.0, 8.5],
            "pluie_24h_mm": [0.0, 0.5, 0.0, 0.0, 8.0, 5.0, 6.0],
            "etp_mm": [0.5, 0.4, 0.3, 0.5, 0.8, 1.0, 1.2],
        },
        index=idx,
    )


def quotidien_ete() -> pd.DataFrame:
    """Scénario été — 7 jours synthétiques.

    - Nuits chaudes (13-16 °C) → aération nuit tunnels
    - Pas de gel
    - 2 jours pluvieux consécutifs (8 + 10 mm) → fenêtre pluvieuse
    - Reste sec, ETP forte (5 mm/j) → déficit + demande évap tunnel
    """
    idx = pd.date_range("2026-07-15", periods=7, freq="D")
    return pd.DataFrame(
        {
            "t_min_celsius": [14.0, 15.0, 16.0, 13.0, 14.0, 15.0, 16.0],
            "t_max_celsius": [28.0, 30.0, 27.0, 29.0, 31.0, 28.0, 27.0],
            "t_moy_celsius": [21.0, 22.5, 21.5, 21.0, 22.5, 21.5, 21.5],
            "pluie_24h_mm": [0.0, 0.0, 8.0, 10.0, 0.0, 0.0, 0.0],
            "etp_mm": [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
        },
        index=idx,
    )


def today_hiver() -> pd.Timestamp:
    """Date de référence hiver pour les fenêtres saisonnières."""
    return pd.Timestamp("2026-01-15")


def today_ete() -> pd.Timestamp:
    """Date de référence été pour les fenêtres saisonnières."""
    return pd.Timestamp("2026-07-15")
