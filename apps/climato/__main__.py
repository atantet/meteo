"""Point d'entrée App 3 Climato — preview locale du rapport Quarto.

Usage :
    python -m apps.climato                        # rend report.html dans apps/climato/
    python -m apps.climato --preview /tmp/c.html  # copie aussi vers ce chemin
    python -m apps.climato --open                 # ouvre le HTML après build

Pipeline :

1. Vérifie que ``quarto`` est dans le PATH (cf. README installation).
2. Lance ``quarto render apps/climato/report.qmd --to html``.
3. Copie la sortie vers le chemin demandé si ``--preview`` fourni.
4. Ouvre via ``xdg-open`` si ``--open``.

Le rendu est identique à celui publié sur GitHub Pages — c'est le
même binaire Quarto.

Exit code :
- 0 : succès.
- 1 : quarto introuvable.
- 2 : échec du render.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

REPORT_QMD = Path("apps/climato/report.qmd")
REPORT_HTML = Path("apps/climato/report.html")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preview",
        type=Path,
        help="Chemin de copie du HTML rendu (ex. /tmp/climato.html).",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Ouvre le HTML après build via xdg-open.",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help="Mode preview live (quarto preview) avec auto-reload sur "
        "changement du .qmd. Lance un serveur local jusqu'à Ctrl-C.",
    )
    args = parser.parse_args()

    if shutil.which("quarto") is None:
        log.error(
            "Binaire `quarto` introuvable dans le PATH. "
            "Installer via le tarball officiel (voir README, section App 3 Climato), "
            "ou recharger le shell si quarto vient d'être installé : `source ~/.bashrc`."
        )
        return 1

    # QUARTO_PYTHON force Quarto à utiliser le Python conda meteo pour
    # exécuter les chunks Python du .qmd. Sans ça, il pioche le
    # premier python du PATH (souvent un venv sans nos deps).
    import os

    env = os.environ.copy()
    if "QUARTO_PYTHON" not in env:
        env["QUARTO_PYTHON"] = sys.executable

    if args.server:
        log.info("Quarto preview server (Ctrl-C pour arrêter).")
        try:
            return subprocess.call(
                ["quarto", "preview", str(REPORT_QMD), "--no-browser"],
                env=env,
            )
        except KeyboardInterrupt:
            return 0

    log.info("Rendu Quarto : %s → HTML (QUARTO_PYTHON=%s)", REPORT_QMD, env["QUARTO_PYTHON"])
    try:
        subprocess.run(
            ["quarto", "render", str(REPORT_QMD), "--to", "html"],
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        log.error("Échec du rendu Quarto (exit %d). Voir la sortie ci-dessus.", e.returncode)
        return 2

    if not REPORT_HTML.exists():
        log.error("HTML attendu introuvable : %s", REPORT_HTML)
        return 2

    if args.preview is not None:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPORT_HTML, args.preview)
        log.info("Copie HTML : %s", args.preview)
        cible = args.preview
    else:
        cible = REPORT_HTML

    if args.open:
        try:
            subprocess.Popen(["xdg-open", str(cible)])
            log.info("Ouverture via xdg-open : %s", cible)
        except FileNotFoundError:
            log.warning("xdg-open absent — ouvrir manuellement : %s", cible)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
