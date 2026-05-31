"""Tests `apps.veille.config` — chargement YAML + override + secrets env."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def test_load_yaml_basic(tmp_path: Path) -> None:
    from apps.veille.config import load_yaml

    p = tmp_path / "test.yaml"
    p.write_text("foo: 1\nbar:\n  baz: 2\n")
    result = load_yaml(p)
    assert result == {"foo": 1, "bar": {"baz": 2}}


def test_load_yaml_empty_returns_empty_dict(tmp_path: Path) -> None:
    from apps.veille.config import load_yaml

    p = tmp_path / "empty.yaml"
    p.write_text("")
    assert load_yaml(p) == {}


def test_deep_merge_recursive(tmp_path: Path) -> None:
    from apps.veille.config import _deep_merge

    base = {"a": 1, "b": {"c": 2, "d": 3}, "e": [1, 2]}
    override = {"b": {"c": 20, "f": 4}, "e": [9]}
    merged = _deep_merge(base, override)
    # b.c écrasé, b.d préservé, b.f ajouté.
    assert merged == {"a": 1, "b": {"c": 20, "d": 3, "f": 4}, "e": [9]}
    # base non modifié.
    assert base == {"a": 1, "b": {"c": 2, "d": 3}, "e": [1, 2]}


def test_load_config_defaut_seul(tmp_path: Path) -> None:
    """Sans override local, retourne le YAML défaut tel quel."""
    from apps.veille.config import load_config

    default = tmp_path / "default.yaml"
    default.write_text("site:\n  latitude: 48.5\n  longitude: -1.6\n")
    config = load_config(default_path=default, local_override_path=None)
    assert config == {"site": {"latitude": 48.5, "longitude": -1.6}}


def test_load_config_avec_override(tmp_path: Path) -> None:
    """Override local écrase partiellement le défaut."""
    from apps.veille.config import load_config

    default = tmp_path / "default.yaml"
    override = tmp_path / "local.yaml"
    default.write_text(
        "site:\n  latitude: 48.5\n  longitude: -1.6\nalertes:\n  gel:\n    seuil_celsius: -2.0\n"
    )
    override.write_text("alertes:\n  gel:\n    seuil_celsius: -1.0\n")
    config = load_config(default_path=default, local_override_path=override)
    # site inchangé, seuil gel écrasé.
    assert config["site"]["latitude"] == 48.5
    assert config["alertes"]["gel"]["seuil_celsius"] == -1.0


def test_load_config_override_absent_ignore_silencieusement(tmp_path: Path) -> None:
    from apps.veille.config import load_config

    default = tmp_path / "default.yaml"
    default.write_text("foo: 1\n")
    inexistant = tmp_path / "inexistant.yaml"
    config = load_config(default_path=default, local_override_path=inexistant)
    assert config == {"foo": 1}


def test_get_secret_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.veille.config import get_secret

    monkeypatch.setenv("FOO_BAR_42", "valeur")
    assert get_secret("FOO_BAR_42") == "valeur"


def test_get_secret_absent_raise_configerror(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.veille.config import ConfigError, get_secret

    monkeypatch.delenv("VARIABLE_INEXISTANTE_12345", raising=False)
    with pytest.raises(ConfigError):
        get_secret("VARIABLE_INEXISTANTE_12345")


def test_get_secret_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.veille.config import get_secret

    monkeypatch.delenv("MA_VAR_AVEC_DEFAUT", raising=False)
    assert get_secret("MA_VAR_AVEC_DEFAUT", default="par_defaut") == "par_defaut"


def test_load_smtp_secrets_succes(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.veille.config import load_smtp_secrets

    monkeypatch.setenv("VEILLE_SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("VEILLE_SMTP_PORT", "587")
    monkeypatch.setenv("VEILLE_SMTP_USER", "test@gmail.com")
    monkeypatch.setenv("VEILLE_SMTP_PASSWORD", "app_password_16_chars")
    monkeypatch.setenv("VEILLE_EMAIL_FROM", "test@gmail.com")
    monkeypatch.setenv("VEILLE_EMAIL_TO", "alexis@example.com, equipe@example.com")

    secrets = load_smtp_secrets()
    assert secrets["host"] == "smtp.gmail.com"
    assert secrets["port"] == 587
    assert secrets["email_to"] == ["alexis@example.com", "equipe@example.com"]


def test_load_config_defaut_repo(tmp_path: Path) -> None:
    """Le YAML défaut versionné doit charger et exposer les sections attendues."""
    from apps.veille.config import DEFAULT_CONFIG_PATH, load_config

    config = load_config(default_path=DEFAULT_CONFIG_PATH, local_override_path=None)
    # Sections requises dans le YAML.
    for key in (
        "site",
        "planification",
        "source_meteo",
        "alertes",
        "indicateurs",
        "email",
        "diffusion",
    ):
        assert key in config, f"Section manquante : {key}"
    # Site = La Petite Claye.
    assert config["site"]["latitude"] == pytest.approx(48.5420)
    assert config["planification"]["cron_utc"] == "00 5 * * *"
    assert config["source_meteo"]["horizon_max_jours"] == 2
