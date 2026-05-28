"""Tests unitaires pour les fonctions pures de `meteo_socle.sources.meteofrance`.

Ne couvre que les fonctions sans réseau (conversions d'unités,
renommage de variables, construction de codes département depuis IDs
stations). Les fonctions IO (`demande`, `compiler_*`) demandent une
clé API Météo-France et seront testées en intégration ultérieurement.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _socle_or_skip():
    try:
        from meteo_socle.sources import meteofrance as mf
    except ImportError:
        pytest.skip(
            "meteo_socle.sources.meteofrance non encore implémenté (Phase B à venir, cf. ADR-0003)"
        )
    return mf


def test_client_construction_dpclim() -> None:
    """Client('DPClim') expose les bonnes étiquettes et conversions."""
    mf = _socle_or_skip()
    client = mf.Client("DPClim")
    assert client.api == "DPClim"
    assert client.id_station_label == "id"
    assert client.time_label == "DATE"
    assert client.id_station_donnee_label == "POSTE"
    assert "GLO" in client.variables_labels["horaire"].values()


def test_client_construction_dpobs() -> None:
    """Client('DPObs') diffère légèrement de DPClim sur les étiquettes."""
    mf = _socle_or_skip()
    client = mf.Client("DPObs")
    assert client.api == "DPObs"
    assert client.id_station_label == "Id_station"
    assert client.time_label == "validity_time"


def test_client_api_invalide() -> None:
    """Une API non listée doit lever ValueError."""
    mf = _socle_or_skip()
    with pytest.raises(ValueError):
        mf.Client("DPInexistant")


def test_convertir_unites_dpclim() -> None:
    """Conversion des unités raw DPClim → SI."""
    mf = _socle_or_skip()
    client = mf.Client("DPClim")
    df = pd.DataFrame(
        {
            "temperature_2m": [10.0, 20.0],
            "humidite_relative": [50.0, 80.0],
            "vitesse_vent_10m": [3.0, 5.0],
            "rayonnement_global": [50.0, 100.0],
            "precipitation": [0.0, 1.5],
            "etp": [0.1, 0.4],
        }
    )
    result = mf.convertir_unites(client, df)
    # T : °C → K (+ 273.15)
    np.testing.assert_array_almost_equal(result["temperature_2m"].to_numpy(), [283.15, 293.15])
    # HR : % → fraction (/ 100)
    np.testing.assert_array_almost_equal(result["humidite_relative"].to_numpy(), [0.5, 0.8])
    # Vent : identité
    np.testing.assert_array_almost_equal(result["vitesse_vent_10m"].to_numpy(), [3.0, 5.0])
    # Rayonnement : J/cm²/h → J/m²/h (× 1e4)
    np.testing.assert_array_almost_equal(
        result["rayonnement_global"].to_numpy(), [500000.0, 1000000.0]
    )
    # Pluie et ETP : identité
    np.testing.assert_array_almost_equal(result["precipitation"].to_numpy(), [0.0, 1.5])


def test_convertir_unites_dpobs() -> None:
    """Conversion DPObs : seule l'humidité relative est convertie (% → fraction)."""
    mf = _socle_or_skip()
    client = mf.Client("DPObs")
    df = pd.DataFrame(
        {
            "temperature_2m": [283.15],
            "humidite_relative": [80.0],
            "vitesse_vent_10m": [4.0],
            "rayonnement_global": [500000.0],
            "precipitation": [0.0],
            "etp": [0.05],
        }
    )
    result = mf.convertir_unites(client, df)
    # DPObs : T déjà en K, rayonnement déjà en J/m², vent identité, HR convertie.
    assert result["temperature_2m"].iloc[0] == 283.15
    assert result["humidite_relative"].iloc[0] == 0.8
    assert result["rayonnement_global"].iloc[0] == 500000.0


def test_renommer_variables_dpclim_horaire() -> None:
    """Le renommage transforme les codes MF (GLO, T, U, FF, RR1) en noms standards."""
    mf = _socle_or_skip()
    client = mf.Client("DPClim")
    df = pd.DataFrame({"GLO": [100.0], "T": [10.0], "U": [80.0], "FF": [3.0], "RR1": [0.0]})
    result = mf.renommer_variables(client, df, "horaire")
    assert "rayonnement_global" in result.columns
    assert "temperature_2m" in result.columns
    assert "humidite_relative" in result.columns
    assert "vitesse_vent_10m" in result.columns
    assert "precipitation" in result.columns


def test_liste_id_stations_vers_liste_id_departements() -> None:
    """Le département est le quotient entier ID // 1_000_000."""
    mf = _socle_or_skip()
    df = pd.DataFrame(index=pd.Index([35228001, 35110003, 50410003, 35044001, 22372001], name="id"))
    result = mf.liste_id_stations_vers_liste_id_departements(df)
    # Unique trié : 22, 35, 50
    np.testing.assert_array_equal(result, [22, 35, 50])
