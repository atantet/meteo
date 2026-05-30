"""Tests `apps.climato` — config, climatologie, donnees."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


# ---------- Config ----------


def test_load_config_defaut_repo() -> None:
    from apps.climato.config import DEFAULT_CONFIG_PATH, load_config

    config = load_config(default_path=DEFAULT_CONFIG_PATH, local_override_path=None)
    for key in ("site", "source_meteo", "periodes", "indicateurs", "rapport"):
        assert key in config, f"Section manquante : {key}"
    assert config["periodes"]["normale_debut"] == 1991
    assert config["periodes"]["normale_fin"] == 2020
    assert config["source_meteo"]["modele"] == "cerra"


# ---------- Climatologie ----------


def _serie_horaire_2ans() -> pd.DataFrame:
    """2 années horaires (synthétique homogène) pour tests d'agrégation."""
    index = pd.date_range("2019-01-01 00:00+00:00", "2020-12-31 23:00+00:00", freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": 285.0,  # 12 °C constant
            "humidite_relative": 0.7,
            "vitesse_vent_10m": 4.0,
            "rafales_vent_10m": 8.0,
            "rayonnement_global": 0.0,
            "precipitation": 0.1,
        },
        index=index,
    )


def _patch_etp(etp_horaire_mm: float):
    def fake(df, lat, lon, alt):
        return pd.Series(etp_horaire_mm, index=df.index)

    return patch("apps.climato.climatologie.calcul_etp", side_effect=fake)


def test_agreger_quotidien_colonnes_et_ordre() -> None:
    from apps.climato.climatologie import agreger_quotidien

    df = _serie_horaire_2ans()
    with _patch_etp(0.1):
        quot = agreger_quotidien(df, 48.5, -1.6, 30)
    assert list(quot.columns) == [
        "t_min_celsius",
        "t_max_celsius",
        "t_moy_celsius",
        "pluie_mm",
        "etp_mm",
    ]
    # 2 années non-bissextiles ≈ 731 jours (2020 bissextile).
    assert 730 <= len(quot) <= 732


def test_agreger_quotidien_valeurs() -> None:
    from apps.climato.climatologie import agreger_quotidien

    df = _serie_horaire_2ans()
    with _patch_etp(0.1):
        quot = agreger_quotidien(df, 48.5, -1.6, 30)
    # T° constante 12 °C.
    assert quot["t_min_celsius"].iloc[10] == pytest.approx(11.85)
    # Pluie 0.1 mm × 24 h = 2.4 mm/jour.
    assert quot["pluie_mm"].iloc[0] == pytest.approx(2.4)
    # ETP mockée 0.1 mm/h × 24 = 2.4 mm/jour.
    assert quot["etp_mm"].iloc[0] == pytest.approx(2.4, rel=1e-3)


def test_agreger_mensuel() -> None:
    from apps.climato.climatologie import agreger_mensuel, agreger_quotidien

    df = _serie_horaire_2ans()
    with _patch_etp(0.1):
        quot = agreger_quotidien(df, 48.5, -1.6, 30)
    mensuel = agreger_mensuel(quot)
    # MultiIndex (annee, mois).
    assert mensuel.index.names == ["annee", "mois"]
    # 2 ans × 12 mois = 24.
    assert len(mensuel) == 24
    # Pluie de janvier 2019 = 31 jours × 2.4 mm = 74.4 mm.
    assert mensuel.loc[(2019, 1), "pluie"] == pytest.approx(74.4, rel=1e-3)


def test_normale_mensuelle() -> None:
    from apps.climato.climatologie import (
        agreger_mensuel,
        agreger_quotidien,
        normale_mensuelle,
    )

    df = _serie_horaire_2ans()
    with _patch_etp(0.1):
        quot = agreger_quotidien(df, 48.5, -1.6, 30)
    mensuel = agreger_mensuel(quot)
    normale = normale_mensuelle(mensuel, periode=(2019, 2020))
    # Index = 12 mois.
    assert list(normale.index) == list(range(1, 13))
    # Pluie de mars moyenne sur 2 ans = (31 × 2.4 + 31 × 2.4) / 2 ≈ 74.4.
    assert normale.loc[3, "pluie"] == pytest.approx(74.4, rel=1e-3)


def test_jours_caracteristiques_par_annee() -> None:
    from apps.climato.climatologie import jours_caracteristiques_par_annee

    quot = pd.DataFrame(
        {
            "t_min_celsius": [-3.0, 5.0, -1.0],
            "t_max_celsius": [5.0, 35.0, 12.0],
            "pluie_mm": [0.0, 15.0, 5.0],
            "t_moy_celsius": [0.0, 20.0, 5.0],
            "etp_mm": [1.0, 5.0, 2.0],
        },
        index=pd.to_datetime(["2020-01-01", "2020-08-15", "2020-12-25"]),
    )
    jours = jours_caracteristiques_par_annee(quot)
    assert jours.loc[2020, "jours_gel"] == 2  # 2 jours T_min < 0
    assert jours.loc[2020, "jours_canicule"] == 1  # T_max > 30
    assert jours.loc[2020, "jours_pluvieux"] == 1  # pluie > 10


def test_dates_gel_par_annee() -> None:
    from apps.climato.climatologie import dates_gel_par_annee

    # Dernier gel printanier = 1er mai, premier gel automnal = 1er nov.
    quot = pd.DataFrame(
        {
            "t_min_celsius": [-3.0, -1.0, 5.0, 8.0, -2.0, -4.0],
            "t_max_celsius": [0.0, 2.0, 10.0, 12.0, 5.0, 1.0],
            "pluie_mm": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "t_moy_celsius": [-2.0, 0.0, 7.0, 10.0, 2.0, -2.0],
            "etp_mm": [1.0, 1.0, 2.0, 2.0, 1.0, 1.0],
        },
        index=pd.to_datetime(
            ["2020-03-15", "2020-05-01", "2020-06-15", "2020-09-15", "2020-11-01", "2020-12-15"]
        ),
    )
    dates = dates_gel_par_annee(quot)
    assert dates.loc[2020, "dernier_gel_printemps"] == pd.Timestamp("2020-05-01")
    assert dates.loc[2020, "premier_gel_automne"] == pd.Timestamp("2020-11-01")
    assert dates.loc[2020, "saison_sans_gel_jours"] == 184


# ---------- Donnees fetch ----------


def test_fetch_historique_decoupe_lots_annuels() -> None:
    from apps.climato.donnees import fetch_historique

    fake_source = MagicMock()

    # Chaque appel renvoie un mini-DataFrame d'1 ligne.
    def fake_obtenir(latitude, longitude, start_date, end_date):
        return pd.DataFrame(
            {"temperature_2m": [285.0]},
            index=pd.DatetimeIndex([f"{start_date}T00:00:00Z"], tz="UTC"),
        )

    fake_source.obtenir_historique.side_effect = fake_obtenir

    df = fetch_historique(
        48.5,
        -1.6,
        annee_debut=2018,
        annee_fin=2020,
        source=fake_source,
        delai_entre_lots_s=0,
    )
    # 3 ans → 3 appels.
    assert fake_source.obtenir_historique.call_count == 3
    assert len(df) == 3


# ---------- Cache parquet ----------


def test_charger_historique_cache_lecture(tmp_path) -> None:
    from apps.climato.donnees import CACHE_PATH, charger_historique_cache

    # Crée un faux cache.
    chemin = tmp_path / CACHE_PATH
    chemin.parent.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2020-01-01", periods=24, freq="h", tz="UTC")
    pd.DataFrame({"temperature_2m": range(24)}, index=idx).to_parquet(chemin)

    df = charger_historique_cache(repo_root=tmp_path)
    assert len(df) == 24
    assert df.index.tz is not None


def test_charger_historique_cache_filtre_annee(tmp_path) -> None:
    from apps.climato.donnees import CACHE_PATH, charger_historique_cache

    chemin = tmp_path / CACHE_PATH
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # 3 ans, 1 valeur/an.
    idx = pd.DatetimeIndex(["2018-06-15", "2019-06-15", "2020-06-15"], tz="UTC")
    pd.DataFrame({"temperature_2m": [10.0, 11.0, 12.0]}, index=idx).to_parquet(chemin)

    df = charger_historique_cache(repo_root=tmp_path, annee_debut=2019, annee_fin=2020)
    assert len(df) == 2
    assert df.index.year.min() == 2019


def test_charger_historique_cache_absent(tmp_path) -> None:
    from apps.climato.donnees import charger_historique_cache

    with pytest.raises(FileNotFoundError, match="refresh_cache_climato"):
        charger_historique_cache(repo_root=tmp_path)
