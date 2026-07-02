"""Tests bulletin eau : anomalie pluie (pur) + composition email (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.bulletin_eau_mensuel.donnees import (  # noqa: E402
    AnomaliePluie,
    BulletinEau,
    calcul_anomalie_pluie,
)
from apps.bulletin_eau_mensuel.email import (  # noqa: E402
    composer_bulletin_email,
    composer_html,
)
from meteo_socle.sources.era5_cds import Era5Cds  # noqa: E402
from meteo_socle.sources.hubeau_piezo import parser_etat_nappe  # noqa: E402
from meteo_socle.sources.vigieau import parser_restrictions  # noqa: E402

# ----- Era5Cds._parse_nc (offline) -----


def test_era5_cds_parse_nc(tmp_path: Path) -> None:
    """_parse_nc : netCDF synthétique → série quotidienne en mm correcte."""
    xr = pytest.importorskip("xarray")
    lat, lon = 48.5, -1.5
    # 3 jours × 24 h = 72 valeurs à 0.001 m/h = 1 mm/h → 24 mm/j attendus.
    times = pd.date_range("2024-06-01", periods=72, freq="h")  # tz-naïf comme ERA5 natif
    tp_vals = np.full(len(times), 0.001, dtype="float32")
    ds = xr.Dataset(
        {"tp": (["time", "latitude", "longitude"], tp_vals[:, np.newaxis, np.newaxis])},
        coords={"time": times, "latitude": [lat], "longitude": [lon]},
    )
    nc_path = str(tmp_path / "era5_test.nc")
    ds.to_netcdf(nc_path)

    s = Era5Cds()._parse_nc(nc_path, lat, lon)
    assert len(s) == 3
    assert abs(s.iloc[0] - 24.0) < 0.5  # 24 h × 1 mm/h = 24 mm


# ----- Anomalie pluie -----


def test_anomalie_pluie_excedent() -> None:
    fin = pd.Timestamp("2024-06-30")
    obs = pd.Series(2.0, index=pd.date_range(fin - pd.Timedelta(days=89), fin, freq="D"))
    ref = pd.Series(1.0, index=pd.date_range("2000-01-01", "2002-12-31", freq="D"))
    a = calcul_anomalie_pluie(obs, ref, fin, fenetre_jours=90)
    assert a is not None
    assert a.cumul_mm == 180.0
    assert a.normale_mm == 90.0  # 3 ans, fenêtre 90 j à 1 mm
    assert a.ecart_pct == 100
    assert a.classe == "excédentaire"
    assert (a.ref_debut_annee, a.ref_fin_annee) == (2000, 2002)


def test_anomalie_pluie_deficit_et_normale() -> None:
    fin = pd.Timestamp("2024-06-30")
    ref = pd.Series(1.0, index=pd.date_range("2000-01-01", "2001-12-31", freq="D"))
    # Déficit : 0,5 mm/j → 45 mm vs 90.
    obs_def = pd.Series(0.5, index=pd.date_range(fin - pd.Timedelta(days=89), fin, freq="D"))
    assert calcul_anomalie_pluie(obs_def, ref, fin).classe == "déficitaire"
    # Normale : 1 mm/j → 90 vs 90 (écart 0 %).
    obs_norm = pd.Series(1.0, index=pd.date_range(fin - pd.Timedelta(days=89), fin, freq="D"))
    a = calcul_anomalie_pluie(obs_norm, ref, fin)
    assert a.ecart_pct == 0
    assert a.classe == "normale"


def test_anomalie_pluie_obs_vide() -> None:
    ref = pd.Series(1.0, index=pd.date_range("2000-01-01", "2001-12-31", freq="D"))
    assert calcul_anomalie_pluie(pd.Series(dtype=float), ref, pd.Timestamp("2024-06-30")) is None


# ----- Composition email (pipeline offline) -----


def _bulletin_complet() -> BulletinEau:
    nappe = parser_etat_nappe(
        [
            {"date_mesure": "2021-06-01", "niveau_nappe_eau": 76.0, "profondeur_nappe": 11.0},
            {"date_mesure": "2022-06-01", "niveau_nappe_eau": 78.0, "profondeur_nappe": 9.0},
            {"date_mesure": "2024-06-01", "niveau_nappe_eau": 77.1, "profondeur_nappe": 9.6},
        ],
        now=pd.Timestamp("2024-06-05"),
    )
    restrictions = parser_restrictions([])  # aucune en vigueur
    pluie = AnomaliePluie(
        debut=pd.Timestamp("2024-04-01"),
        fin=pd.Timestamp("2024-06-30"),
        fenetre_jours=90,
        cumul_mm=120.0,
        normale_mm=150.0,
        ref_debut_annee=1991,
        ref_fin_annee=2020,
    )
    return BulletinEau(
        genere_le=pd.Timestamp("2024-07-01"),
        commune_insee="35216",
        nom_station_nappe="Piézomètre du Calvaire, Bonnemain",
        nappe=nappe,
        restrictions=restrictions,
        pluie=pluie,
    )


def test_compose_email_complet() -> None:
    email = composer_bulletin_email(_bulletin_complet())
    assert "Bulletin eau" in email.sujet
    assert "sans restriction" in email.sujet
    html = email.html
    assert "État de la nappe" in html
    assert "m NGF" in html
    assert "Aucune restriction" in html
    assert "Pluie récente vs normale" in html
    assert "1991-2020" in html
    # Caveat proxy présent (honnêteté).
    assert "pas le débit de votre forage" in html


def test_compose_email_degradation_tout_indispo() -> None:
    vide = BulletinEau(
        genere_le=pd.Timestamp("2024-07-01"),
        commune_insee="35216",
        nom_station_nappe="X",
        nappe=None,
        restrictions=None,
        pluie=None,
    )
    html = composer_html(vide)
    assert "Aucune donnée disponible" in html
    # Le sujet reste émis même sans pilier.
    assert "Bulletin eau" in composer_bulletin_email(vide).sujet
