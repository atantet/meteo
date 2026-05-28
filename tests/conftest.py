"""Configuration pytest commune.

Insère `src/` dans le PYTHONPATH pour que `import meteo_socle...`
fonctionne sans `pip install -e .` (utile en dev local et CI léger).
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
