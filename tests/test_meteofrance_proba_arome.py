"""Test offline de la proba PE-AROME (sans réseau).

On monte les primitives WCS et on vérifie que la série sort en **%** (identité,
pas de conversion), bien nommée et bornée, plus le garde-fou de seuil.
"""

from __future__ import annotations

import pandas as pd
import pytest

from meteo_socle.sources import meteofrance_proba_arome as mpa


@pytest.fixture
def _serie(monkeypatch):
    run = pd.Timestamp("2026-06-15T00:00:00Z")
    echeances = [run + pd.Timedelta(hours=h) for h in (6, 12, 18, 24, 60)]  # +60 h hors 48 h
    monkeypatch.setattr(mpa, "_bearer", lambda *a, **k: "tok")
    monkeypatch.setattr(mpa, "_echeances", lambda *a, **k: echeances)
    # Proba synthétique = 25 % constant (déjà en %, identité attendue).
    monkeypatch.setattr(mpa, "_valeur_point", lambda *a, **k: 25.0)
    return mpa.MeteoFranceProbaArome(basic="x:y").obtenir_proba(run, 48.54, -1.61, horizon_jours=2)


def test_serie_pourcent_identite(_serie: pd.Series) -> None:
    assert _serie.name == "probabilite_pluie_pct"
    assert (_serie == 25.0).all()  # % tel quel, pas de ÷100
    assert _serie.between(0, 100).all()


def test_filtre_horizon(_serie: pd.Series) -> None:
    # horizon 2 j → +60 h exclu ; reste +6..+24 h.
    assert _serie.index.max() <= pd.Timestamp("2026-06-17T00:00:00Z")
    assert len(_serie) == 4


def test_seuil_invalide() -> None:
    with pytest.raises(ValueError, match="indisponible"):
        mpa.MeteoFranceProbaArome(basic="x:y").obtenir_proba(
            pd.Timestamp("2026-06-15T00:00:00Z"), 48.54, -1.61, fenetre_h=6, seuil_mm=3
        )


def test_coverage_prefixe() -> None:
    assert mpa._coverage_prefixe(6, 1) == "N_PROBA_PRECI06_1__GROUND_OR_WATER_SURFACE"
    assert mpa._coverage_prefixe(12, 10) == "N_PROBA_PRECI12_10__GROUND_OR_WATER_SURFACE"
