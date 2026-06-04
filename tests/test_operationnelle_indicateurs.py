"""Tests `apps.operationnelle.indicateurs` — agrégation quotidienne."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


CONFIG_TEST = {
    "site": {"latitude": 48.5420, "longitude": -1.6155, "altitude": 30, "tz": "Europe/Paris"},
}


def _prevision(
    duree_h: int = 24 * 7,
    debut: str = "2024-06-15 00:00:00+00:00",
    t_celsius: float = 15.0,
    pluie_h_mm: float = 0.0,
    humidite: float = 0.7,
    rayonnement_jh: float = 0.0,
    vent_ms: float = 5.0,
    rafales_ms: float = 9.0,
) -> pd.DataFrame:
    index = pd.date_range(debut, periods=duree_h, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(duree_h, t_celsius + 273.15),
            "humidite_relative": np.full(duree_h, humidite),
            "vitesse_vent_10m": np.full(duree_h, vent_ms),
            "rafales_vent_10m": np.full(duree_h, rafales_ms),
            "rayonnement_global": np.full(duree_h, rayonnement_jh),
            "precipitation": np.full(duree_h, pluie_h_mm),
        },
        index=index,
    )


def _patch_etp(etp_horaire_mm: float):
    def fake(df, lat, lon, alt):
        return pd.Series(etp_horaire_mm, index=df.index)

    return patch("apps.operationnelle.indicateurs.calcul_etp", side_effect=fake)


def test_quotidien_colonnes_et_index() -> None:
    from apps.operationnelle.indicateurs import calculer_indicateurs_quotidiens

    prev = _prevision()
    with _patch_etp(0.1):
        q = calculer_indicateurs_quotidiens(prev, CONFIG_TEST)
    # Vérif présence des colonnes principales (autres colonnes
    # optionnelles : direction_vent_*, t_moy_normale_celsius,
    # ecart_normale_celsius ; selon la dispo des fixtures climato).
    for col in (
        "t_min_celsius",
        "t_max_celsius",
        "t_moy_celsius",
        "pluie_24h_mm",
        "rafales_max_kmh",
        "etp_mm",
        "bilan_eau_cumul_mm",
    ):
        assert col in q.columns
    # Index = date (sans heure).
    assert q.index.name == "date"
    # 7 jours de prévision → 8 dates côté locale (split nuit Paris).
    assert 7 <= len(q) <= 8


def test_quotidien_valeurs_homogenes() -> None:
    """Données plates → T° min = max = constante, pluie nulle, ETP mockée."""
    from apps.operationnelle.indicateurs import calculer_indicateurs_quotidiens

    prev = _prevision(t_celsius=15.0)
    with _patch_etp(0.1):
        q = calculer_indicateurs_quotidiens(prev, CONFIG_TEST)
    # Sur un jour complet :
    jour_complet = q.iloc[1] if len(q) > 1 else q.iloc[0]
    assert jour_complet["t_min_celsius"] == pytest.approx(15.0)
    assert jour_complet["t_max_celsius"] == pytest.approx(15.0)
    assert jour_complet["pluie_24h_mm"] == pytest.approx(0.0)
    assert jour_complet["rafales_max_kmh"] == pytest.approx(32.4)
    # ETP mockée : 0.1 mm/h × 24 = 2.4 mm/jour.
    assert jour_complet["etp_mm"] == pytest.approx(2.4, rel=1e-3)


def test_quotidien_bilan_eau_cumul_croit_quand_etp_pluie_negatif() -> None:
    """Sans pluie + ETP positive → bilan cumulé décroit jour après jour."""
    from apps.operationnelle.indicateurs import calculer_indicateurs_quotidiens

    prev = _prevision(pluie_h_mm=0.0)
    with _patch_etp(0.2):
        q = calculer_indicateurs_quotidiens(prev, CONFIG_TEST)
    # Bilan cumulé strictement décroissant.
    diffs = q["bilan_eau_cumul_mm"].diff().dropna()
    assert (diffs < 0).all()


def test_quotidien_filtre_now_utc() -> None:
    """Les heures antérieures à now_utc sont écartées."""
    from apps.operationnelle.indicateurs import calculer_indicateurs_quotidiens

    prev = _prevision(duree_h=48)
    now = pd.Timestamp("2024-06-15 23:00:00+00:00")
    with _patch_etp(0.1):
        q = calculer_indicateurs_quotidiens(prev, CONFIG_TEST, now_utc=now)
    # Seulement les heures à partir de 23:00 UTC le 15 juin → le 15
    # juin a 1-2 heures, le 16 est complet, le 17 démarre.
    assert len(q) <= 3


def test_quotidien_vide_raise() -> None:
    from apps.operationnelle.indicateurs import calculer_indicateurs_quotidiens

    prev = _prevision(duree_h=24)
    now = pd.Timestamp("2024-06-30 00:00:00+00:00")
    with pytest.raises(ValueError):
        calculer_indicateurs_quotidiens(prev, CONFIG_TEST, now_utc=now)


def test_normales_t_min_et_t_max_jointees_si_csv_present() -> None:
    """Quand la CSV normale_jour est dispo, t_min/t_max/t_moy normales jointées."""
    from apps.operationnelle.indicateurs import calculer_indicateurs_quotidiens

    prev = _prevision()
    with _patch_etp(0.1):
        q = calculer_indicateurs_quotidiens(prev, CONFIG_TEST)
    # La CSV normale_jour est commitée dans le repo, donc les 3 colonnes
    # devraient apparaître. Si absente, ce test détectera la régression.
    for col in ("t_min_normale_celsius", "t_max_normale_celsius", "t_moy_normale_celsius"):
        assert col in q.columns, f"Colonne normale manquante : {col}"


def test_jours_complets_filtre_partiels() -> None:
    """``jours_complets_seulement`` enlève les jours avec couverture < 23 h."""
    from apps.operationnelle.indicateurs import (
        calculer_indicateurs_quotidiens,
        jours_complets_seulement,
    )

    # Démarrer la prévision à 22h UTC = 0h Paris en été → 1er jour
    # local n'a que 2 h de couverture.
    prev = _prevision(duree_h=48, debut="2024-06-14 22:00:00+00:00")
    with _patch_etp(0.1):
        q = calculer_indicateurs_quotidiens(prev, CONFIG_TEST)
    filtered = jours_complets_seulement(q, prev)
    # Au moins 1 jour partiel filtré.
    assert len(filtered) < len(q)
