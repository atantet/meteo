"""Apps utilisateur du projet meteo.

Au moment de l'import, ajoute ``src/`` au PYTHONPATH pour rendre le
package ``meteo_socle`` importable sans nécessiter ``pip install -e .``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
