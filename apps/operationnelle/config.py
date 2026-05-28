"""Loader de configuration pour l'App 2 Opérationnelle (Streamlit).

Charge `config/operationnelle.yaml` + override local
`config/operationnelle.local.yaml` (gitignored).

Mutualise les utilitaires YAML / merge avec `apps.veille.config` —
même méthode pour rester cohérent entre apps.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# On réutilise les utilitaires bas niveau de l'app veille — pure
# mécanique YAML/merge, pas spécifique au domaine.
from apps.veille.config import REPO_ROOT, _deep_merge, load_yaml

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "operationnelle.yaml"
LOCAL_OVERRIDE_PATH = REPO_ROOT / "config" / "operationnelle.local.yaml"


def load_config(
    default_path: Path | str = DEFAULT_CONFIG_PATH,
    local_override_path: Path | str | None = LOCAL_OVERRIDE_PATH,
) -> dict[str, Any]:
    """Charge la config Opérationnelle, défaut + override local si présent."""
    config = load_yaml(default_path)
    if local_override_path is not None:
        p = Path(local_override_path)
        if p.exists():
            config = _deep_merge(config, load_yaml(p))
    return config
