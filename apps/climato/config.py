"""Loader de configuration App 3 Climato (Quarto + Pages)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.veille.config import REPO_ROOT, _deep_merge, load_yaml

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "climato.yaml"
LOCAL_OVERRIDE_PATH = REPO_ROOT / "config" / "climato.local.yaml"


def load_config(
    default_path: Path | str = DEFAULT_CONFIG_PATH,
    local_override_path: Path | str | None = LOCAL_OVERRIDE_PATH,
) -> dict[str, Any]:
    """Charge la config Climato (défaut + override local optionnel)."""
    config = load_yaml(default_path)
    if local_override_path is not None:
        p = Path(local_override_path)
        if p.exists():
            config = _deep_merge(config, load_yaml(p))
    return config
