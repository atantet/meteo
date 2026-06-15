"""Test d'intégration **offline** d'AROME direct MF (sans réseau).

Le fetch WCS (OAuth + GetCoverage + GRIB) nécessite réseau + clé DP : non testé
en CI. On injecte ici une **prévision synthétique** (valeurs brutes en unités GRIB
MF) en montant ``_valeur_point``/``_echeances``/``_bearer``, et on vérifie que
``obtenir_run`` sort des **unités socle** correctes — surtout les conversions
fragiles (HR % → fraction, **nébulosité AROME déjà en fraction**, code de type de
précip passé tel quel, vent U/V → vitesse).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from meteo_socle.sources import meteofrance_arome as mfa

# Valeurs brutes synthétiques par famille de coverage (unités GRIB MF telles
# qu'observées au point le 2026-06-15, cf. smoke diag_arome_getcoverage).
_BRUT = {
    "TEMPERATURE__": 290.0,  # K
    "RELATIVE_HUMIDITY__": 80.0,  # %
    "WIND_SPEED_GUST__": 8.0,  # m/s
    "TOTAL_CLOUD_COVER__": 0.5,  # fraction 0-1 (≠ ARPEGE en %)
    "LOW_CLOUD_COVER__": 0.2,
    "MEDIUM_CLOUD_COVER__": 0.3,
    "HIGH_CLOUD_COVER__": 0.1,
    "PRECIPITATION_TYPE_60_MIN__": 1.0,  # code GRIB 4.201 (1 = pluie)
    "VISIBILITY_MINI_60MIN__": 5000.0,  # m
    "U_COMPONENT_OF_WIND__": 3.0,  # m/s
    "V_COMPONENT_OF_WIND__": 4.0,  # m/s
    "TOTAL_PRECIPITATION__": 0.4,  # mm sur la fenêtre
    "TOTAL_SNOW_PRECIPITATION__": 0.0,  # mm
    "DOWNWARD_SHORT_WAVE_RADIATION_FLUX__": 3.6e6,  # J/m² sur 1 h → 3,6e6/h
}


def _faux_valeur_point(session, token, cid, valid, lat, lon, hauteur, wcs_base=""):
    for prefixe, val in _BRUT.items():
        if cid.startswith(prefixe):
            return val
    raise mfa.ArpegeIndisponibleError(f"coverage inattendu : {cid}")


@pytest.fixture
def _run(monkeypatch):
    run = pd.Timestamp("2026-06-15T00:00:00Z")
    echeances = [run + pd.Timedelta(hours=h) for h in range(4)]  # horaire 0-3 h
    monkeypatch.setattr(mfa, "_bearer", lambda *a, **k: "tok")
    monkeypatch.setattr(mfa, "_echeances", lambda *a, **k: echeances)
    monkeypatch.setattr(mfa, "_valeur_point", _faux_valeur_point)
    return mfa.MeteoFranceArome(basic="x:y").obtenir_run(run, 48.54, -1.61, horizon_jours=1)


def test_colonnes_socle_presentes(_run: pd.DataFrame) -> None:
    for col in (
        "temperature_2m",
        "humidite_relative",
        "cloud_cover",
        "type_precip",
        "visibilite_m",
        "precipitation",
        "vitesse_vent_10m",
        "direction_vent_deg",
    ):
        assert col in _run.columns
    # U/V bruts retirés après dérivation vitesse/direction.
    assert "_u10" not in _run.columns and "_v10" not in _run.columns


def test_conversions_unites(_run: pd.DataFrame) -> None:
    ligne = _run.iloc[-1]  # +3 h (échéance pleine, hors analyse)
    assert ligne["temperature_2m"] == pytest.approx(290.0)  # K, identité
    assert ligne["humidite_relative"] == pytest.approx(0.80)  # % → fraction
    # Nébulosité AROME déjà en fraction → identité (PAS 0.005). Garde-fou clé.
    assert ligne["cloud_cover"] == pytest.approx(0.5)
    assert 0.0 <= ligne["cloud_cover"] <= 1.0
    assert ligne["type_precip"] == pytest.approx(1.0)  # code passé tel quel
    assert ligne["visibilite_m"] == pytest.approx(5000.0)
    assert ligne["vitesse_vent_10m"] == pytest.approx(5.0)  # hypot(3,4)


def test_accumulees_analyse_nulle(_run: pd.DataFrame) -> None:
    # +0 h : pas de fenêtre d'accumulation → 0.
    assert _run.iloc[0]["precipitation"] == 0.0
    # Champs « sans analyse » (type_precip, visibilité, rafale) → NaN à +0 h.
    assert np.isnan(_run.iloc[0]["type_precip"])
    assert np.isnan(_run.iloc[0]["rafales_vent_10m"])


def test_cloud_cover_pas_pct_frac() -> None:
    # Régression : le mapping doit déclarer la nébulosité « frac », pas « pct_frac »
    # (sinon ÷100 → ciel toujours clair). Vérifie aussi les couches.
    for col in ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high"):
        assert mfa._VARS_INSTANT[col][2] == "frac"
    assert mfa._VARS_INSTANT["humidite_relative"][2] == "pct_frac"
