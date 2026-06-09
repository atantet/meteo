"""Point d'entrée atelier irrigation — lance Streamlit localement.

Usage :
    python -m apps.atelier_irrigation           # http://localhost:8501
    python -m apps.atelier_irrigation --port 8502

Équivalent à : ``streamlit run apps/atelier_irrigation/streamlit_app.py``.

Exit code :
- 0 : Streamlit lancé jusqu'à interruption manuelle (Ctrl-C).
- 1 : streamlit absent dans le PATH (env conda meteo non activé).
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

APP_PATH = Path("apps/atelier_irrigation/streamlit_app.py")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8501, help="Port HTTP (défaut 8501).")
    parser.add_argument(
        "--headless", action="store_true", help="Pas de browser auto-ouvert (utile en remote)."
    )
    args = parser.parse_args()

    if shutil.which("streamlit") is None:
        log.error(
            "Binaire `streamlit` introuvable dans le PATH. "
            "Activer l'env conda : `conda activate meteo`."
        )
        return 1

    cmd = ["streamlit", "run", str(APP_PATH), "--server.port", str(args.port)]
    if args.headless:
        cmd += ["--server.headless", "true"]

    log.info("Lance Streamlit : %s", " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
