"""Preview de la 48 h **portail-api** (flag ON forcé) — validation avant bascule (ADR-0021).

Génère les DEUX previews (matin + après-midi) du mail Veille avec la 48 h servie
par le portail-api direct (AROME HD + PE-AROME proba + DPVigilance), au lieu du
webservice. Le flag ``veille_portail_api`` est **forcé à true en mémoire** (pas
besoin d'éditer la config). Nécessite la clé DP ``METEOFRANCE_DP_BASIC`` (chargée
depuis ``.env``).

Usage :
    python scripts/preview_veille_portail.py            # ce jour (matin + après-midi)
    python scripts/preview_veille_portail.py 2026-06-16 # date précise (UTC)
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (_REPO_ROOT, _REPO_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pandas as pd  # noqa: E402

from apps.veille.__main__ import executer_veille  # noqa: E402
from apps.veille.config import load_config, load_dotenv_if_present  # noqa: E402

OUT = Path("/tmp")


def main() -> None:
    load_dotenv_if_present()  # charge METEOFRANCE_DP_BASIC depuis .env
    jour = pd.Timestamp(sys.argv[1], tz="UTC") if len(sys.argv) > 1 else pd.Timestamp.now(tz="UTC")
    jour = jour.normalize()

    config = load_config()
    config.setdefault("source_meteo", {})["veille_portail_api"] = True  # flag ON forcé
    config.setdefault("vigilance_mf", {}).setdefault("departement", "35")
    print("Flag portail-api FORCÉ à true (preview).")

    for moment, heure in (("matin", 5), ("apres-midi", 15)):
        now_utc = jour + pd.Timedelta(hours=heure, minutes=30)
        chemin = OUT / f"veille_preview_{moment}.html"
        code = executer_veille(config, secrets=None, now_utc=now_utc, preview_path=str(chemin))
        print(f"  {moment:11} (now={now_utc:%Y-%m-%d %H:%MZ}) → code={code} → {chemin}")


if __name__ == "__main__":
    main()
