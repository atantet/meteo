"""Loader de configuration du bulletin eau mensuel.

Réutilise les helpers de la Veille (merge défaut + override local, secrets
SMTP depuis l'environnement). Le bulletin partage la **même boîte mail**
que la Veille : il s'appuie donc sur les mêmes secrets ``VEILLE_SMTP_*``
(cf. ``apps.veille.config.load_smtp_secrets``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.veille.config import (
    REPO_ROOT,
    ConfigError,
    _deep_merge,
    load_dotenv_if_present,
    load_smtp_secrets,
    load_yaml,
)

__all__ = [
    "ConfigError",
    "load_config",
    "load_dotenv_if_present",
    "load_smtp_secrets",
]

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "bulletin_eau_mensuel.yaml"
LOCAL_OVERRIDE_PATH = REPO_ROOT / "config" / "bulletin_eau_mensuel.local.yaml"


def load_config(
    default_path: Path | str = DEFAULT_CONFIG_PATH,
    local_override_path: Path | str | None = LOCAL_OVERRIDE_PATH,
) -> dict[str, Any]:
    """Charge la config bulletin, défaut + override local si présent."""
    config = load_yaml(default_path)
    if local_override_path is not None:
        p = Path(local_override_path)
        if p.exists():
            config = _deep_merge(config, load_yaml(p))
    return config
