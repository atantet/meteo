"""Loader de configuration pour l'App 1 Veille.

Charge le YAML défaut (`config/veille.yaml`), applique l'override
local (`config/veille.local.yaml`) s'il existe, et expose les secrets
SMTP depuis l'environnement (`.env` ou GitHub Actions Secrets).

Conformément au principe n°1 (publication policy, ADR-0001) et au
principe transverse n°5 (transparence), aucun secret n'est jamais
embarqué dans les fichiers versionnés. Les secrets viennent toujours
de variables d'environnement.

Référence de schéma : `config/veille.yaml` (avec ses commentaires).
"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Racine du projet = parent du dossier `apps/`.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "veille.yaml"
LOCAL_OVERRIDE_PATH = REPO_ROOT / "config" / "veille.local.yaml"


class ConfigError(Exception):
    """Erreur de configuration (clé manquante, secret absent, etc.)."""


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge récursif : ``override`` écrase ``base`` clé par clé.

    Les sous-dictionnaires sont fusionnés ; les listes et scalaires sont
    remplacés. ``base`` n'est pas modifié.
    """
    result = deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_yaml(path: Path | str) -> dict[str, Any]:
    """Charge un fichier YAML en dictionnaire Python (vide si fichier vide)."""
    p = Path(path)
    with p.open() as f:
        return yaml.safe_load(f) or {}


def load_config(
    default_path: Path | str = DEFAULT_CONFIG_PATH,
    local_override_path: Path | str | None = LOCAL_OVERRIDE_PATH,
) -> dict[str, Any]:
    """Charge la config Veille, défaut + override local si présent.

    Parameters
    ----------
    default_path :
        YAML défaut versionné.
    local_override_path :
        YAML override local (gitignored). Ignoré silencieusement s'il
        n'existe pas. Si ``None``, pas de tentative d'override.

    Returns
    -------
    dict
        Configuration résultante après merge profond.
    """
    config = load_yaml(default_path)
    if local_override_path is not None:
        p = Path(local_override_path)
        if p.exists():
            override = load_yaml(p)
            config = _deep_merge(config, override)
    return config


def load_dotenv_if_present(dotenv_path: Path | str | None = None) -> None:
    """Charge ``.env`` du projet dans ``os.environ``, idempotent.

    En GitHub Actions, les Secrets sont déjà injectés dans ``os.environ``
    par le runner — cette fonction est alors no-op si ``.env`` n'existe pas.
    """
    if dotenv_path is None:
        dotenv_path = REPO_ROOT / ".env"
    p = Path(dotenv_path)
    if p.exists():
        load_dotenv(p)


def get_secret(name: str, default: str | None = None) -> str:
    """Lit une variable d'environnement.

    Raises
    ------
    ConfigError
        Si ``default`` est ``None`` et la variable n'existe pas dans
        ``os.environ``.
    """
    value = os.environ.get(name, default)
    if value is None:
        raise ConfigError(
            f"Variable d'environnement requise non définie : {name}. "
            f"Voir .env.example pour le setup."
        )
    return value


def load_smtp_secrets() -> dict[str, Any]:
    """Charge les secrets SMTP depuis l'environnement.

    Returns
    -------
    dict
        Avec clés : ``host``, ``port`` (int), ``user``, ``password``,
        ``email_from``, ``email_to`` (list[str] — split sur virgule).
    """
    return {
        "host": get_secret("VEILLE_SMTP_HOST"),
        "port": int(get_secret("VEILLE_SMTP_PORT")),
        "user": get_secret("VEILLE_SMTP_USER"),
        "password": get_secret("VEILLE_SMTP_PASSWORD"),
        "email_from": get_secret("VEILLE_EMAIL_FROM"),
        "email_to": [e.strip() for e in get_secret("VEILLE_EMAIL_TO").split(",") if e.strip()],
    }
