"""Tests `apps.operationnelle.config`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def test_load_config_defaut_repo() -> None:
    """Le YAML défaut de l'app Opérationnelle expose les sections attendues."""
    from apps.operationnelle.config import DEFAULT_CONFIG_PATH, load_config

    config = load_config(default_path=DEFAULT_CONFIG_PATH, local_override_path=None)
    for key in ("site", "source_meteo", "alertes", "ui"):
        assert key in config, f"Section manquante : {key}"
    assert config["site"]["latitude"] == pytest.approx(48.5420)
    # Double horizon : court (ARPEGE, guides + séries temp) et long
    # (ECMWF, tendance + cartes).
    assert config["source_meteo"]["horizon_court_jours"] == 4
    assert config["source_meteo"]["horizon_long_jours"] == 7
    assert config["source_meteo"]["modele_court"] == "meteofrance_arpege_europe"
    assert config["source_meteo"]["modele_long"] == "ecmwf_ifs025"
    # Cohérence avec App 1 Veille sur les seuils.
    assert config["alertes"]["gel"]["seuil_celsius"] == -2.0


def test_load_config_override_local(tmp_path: Path) -> None:
    from apps.operationnelle.config import load_config

    default = tmp_path / "default.yaml"
    override = tmp_path / "local.yaml"
    default.write_text("site:\n  latitude: 48.5\nalertes:\n  gel:\n    seuil_celsius: -2.0\n")
    override.write_text("alertes:\n  gel:\n    seuil_celsius: -3.0\n")
    config = load_config(default_path=default, local_override_path=override)
    assert config["site"]["latitude"] == 48.5
    assert config["alertes"]["gel"]["seuil_celsius"] == -3.0
