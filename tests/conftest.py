"""Configuration pytest commune.

Insère `src/` dans le PYTHONPATH pour que `import meteo_socle...`
fonctionne sans `pip install -e .` (utile en dev local et CI léger).

Force aussi le backend matplotlib **Agg** : l'env contient PySide6, donc le
backend par défaut est ``qtagg`` qui, en CI **headless** (sans affichage), bloque
à l'import de ``pyplot`` (via ``charts.py``) → pytest pend jusqu'au timeout du job.
Défini ici (avant tout import de matplotlib) pour que la sélection le respecte.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
