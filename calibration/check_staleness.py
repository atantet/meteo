#!/usr/bin/env python
"""Alerte mail si data/calibration/ n'a pas été mis à jour depuis longtemps.

À lancer plus souvent que ``run_pipeline.sh`` (ex. toutes les heures) — ne
fait qu'un ``git log`` local, aucun appel réseau MF/GH. But : détecter un
trou de crontab (machine éteinte/en veille aux créneaux 07:10/19:10) et
inviter à un rattrapage manuel avant qu'un run Veille supplémentaire ne
passe (auquel cas son label MF est perdu définitivement — pas de fetch
rétroactif possible auprès du webservice MF).

Usage
-----
    python calibration/check_staleness.py
    python calibration/check_staleness.py --seuil-h 30
    python calibration/check_staleness.py --dry-run   # affiche sans envoyer

Crontab locale recommandée (plus fréquente que run_pipeline.sh) :
    5 * * * * /home/atantet/.conda/envs/meteo/bin/python \
        /home/atantet/projets/meteo/calibration/check_staleness.py >> /tmp/calib_staleness.log 2>&1
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from apps.veille.config import load_dotenv_if_present, load_smtp_secrets  # noqa: E402
from apps.veille.email import EmailComposed  # noqa: E402
from apps.veille.sender import envoyer  # noqa: E402

_SEUIL_H_DEFAUT = 30  # > 1 créneau raté (12 h), < 2 jours : pas d'alerte sur un seul point manqué


def _dernier_commit_epoch() -> int | None:
    out = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", "data/calibration/"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return int(out) if out else None


def main(seuil_h: int = _SEUIL_H_DEFAUT, dry_run: bool = False) -> None:
    dernier = _dernier_commit_epoch()
    if dernier is None:
        print("Aucun commit trouvé sur data/calibration/ — rien à comparer.")
        return

    ecart_h = (datetime.now(UTC).timestamp() - dernier) / 3600
    if ecart_h <= seuil_h:
        print(f"OK — dernier commit calibration il y a {ecart_h:.1f} h (seuil {seuil_h} h).")
        return

    sujet = f"[Calibration pictos] Pipeline en retard — {ecart_h:.0f} h sans commit"
    texte = (
        f"Aucun commit sur data/calibration/ depuis {ecart_h:.0f} h (seuil {seuil_h} h).\n\n"
        "Le crontab local (07:10/19:10) a probablement raté un ou plusieurs créneaux "
        "(machine éteinte/en veille).\n\n"
        "Rattraper dès que possible pour limiter la perte de points :\n"
        "    bash calibration/run_pipeline.sh\n\n"
        "Au-delà d'un run Veille supplémentaire passé sans rattrapage, le label MF de ce "
        "run est perdu définitivement (pas de fetch rétroactif possible)."
    )
    email = EmailComposed(sujet=sujet, texte=texte, html=f"<pre>{texte}</pre>")

    load_dotenv_if_present()
    secrets = None if dry_run else load_smtp_secrets()
    envoyer(email, secrets=secrets, envoi_reel=not dry_run)
    print(f"Alerte {'(dry-run) ' if dry_run else ''}— {ecart_h:.0f} h sans commit calibration.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--seuil-h", type=int, default=_SEUIL_H_DEFAUT, help="Seuil d'écart en heures (défaut : 30)"
    )
    ap.add_argument("--dry-run", action="store_true", help="Affiche sans envoyer de mail")
    args = ap.parse_args()
    main(seuil_h=args.seuil_h, dry_run=args.dry_run)
