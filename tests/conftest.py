"""Configuration pytest commune.

Insère `src/` (et la racine du dépôt, pour `import apps...`) dans le PYTHONPATH
pour que les imports fonctionnent sans `pip install -e .` (dev local + CI léger).

Force aussi le backend matplotlib **Agg** : l'env contient PySide6, donc le
backend par défaut est ``qtagg`` qui, en CI **headless** (sans affichage), bloque
à l'import de ``pyplot`` (via ``charts.py``) → pytest pend jusqu'au timeout du job.
Défini ici (avant tout import de matplotlib) pour que la sélection le respecte.

Enfin, un fixture **autouse** neutralise le fetch réseau des cartes synoptiques
de la Veille : c'était (avec le webservice MF, depuis retiré) la cause du **hang
CI récurrent**, révélée par le dump faulthandler après fiabilisation de
``ci.yml``. La 48 h portail (AROME/PE-AROME/DPVigilance, ADR-0021) passe par
``assembler_prevision_48h``, que les tests d'orchestration patchent directement.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("MPLBACKEND", "Agg")

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT / "src", REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture(autouse=True)
def _veille_sans_reseau_48h(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub les fetch réseau 48 h de la Veille pour TOUS les tests (zéro réseau).

    ``executer_veille`` appelle ``recuperer_cartes`` (Météociel / Met Office),
    qui était une cause du **hang CI récurrent** (cf. ci.yml). On le neutralise
    (→ ``None``, dégradation gracieuse déjà gérée par le composeur). Les tests
    qui exercent vraiment ce fetch appellent la fonction directement, avec une
    session mockée (``test_veille_cartes_*``) — non affectés par ce stub.
    """
    import apps.veille.__main__ as veille_main

    monkeypatch.setattr(veille_main, "recuperer_cartes", lambda *a, **k: None, raising=False)
