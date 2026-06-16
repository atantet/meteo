"""Preview de la 48 h **portail-api** (flag ON forcé) — validation avant bascule (ADR-0021).

Génère les DEUX previews (matin + après-midi) du mail Veille avec la 48 h servie
par le portail-api direct (AROME HD + PE-AROME proba + DPVigilance). Le flag
``veille_portail_api`` est **forcé à true en mémoire**. **Nécessite la clé DP**
``METEOFRANCE_DP_BASIC`` (chargée depuis ``.env``) — le script le vérifie et le dit.

On force des instants **passés** (les runs visés sont publiés) et ``fallback_mf=True``
(la preview s'écrit toujours, même si la 48 h échoue → tu vois alors l'omission).

Usage :
    python scripts/preview_veille_portail.py            # derniers créneaux matin/après-midi
    python scripts/preview_veille_portail.py 2026-06-16 # date précise (UTC)
"""

from __future__ import annotations

import logging
import os
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


def _instant_passe(jour: pd.Timestamp, heure: int, maintenant: pd.Timestamp) -> pd.Timestamp:
    """Instant ``jour`` à ``heure``:30, ramené à la veille s'il est dans le futur.

    Évite de viser un run pas encore publié (forçant un now_utc futur).
    """
    t = jour + pd.Timedelta(hours=heure, minutes=30)
    return t if t <= maintenant else t - pd.Timedelta(days=1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv_if_present()
    cle = os.environ.get("METEOFRANCE_DP_BASIC", "")
    print(f"Clé DP (METEOFRANCE_DP_BASIC) : {'présente' if cle else 'ABSENTE'}")
    if not cle:
        print(
            "→ Sans clé DP en local, la 48 h portail-api ne peut pas être fetchée : la\n"
            "  preview montrera la 48 h OMISE. Pour une vraie preview flag-ON, lance le\n"
            "  workflow CI dédié (la clé y est en secret) — voir avec l'assistant."
        )

    maintenant = pd.Timestamp.now(tz="UTC")
    jour = (pd.Timestamp(sys.argv[1], tz="UTC") if len(sys.argv) > 1 else maintenant).normalize()

    config = load_config()
    config.setdefault("source_meteo", {})["veille_portail_api"] = True
    config.setdefault("vigilance_mf", {}).setdefault("departement", "35")
    print("Flag portail-api FORCÉ à true (preview).\n")

    for moment, heure in (("matin", 5), ("apres-midi", 15)):
        now_utc = _instant_passe(jour, heure, maintenant)
        chemin = OUT / f"veille_preview_{moment}.html"
        avant = chemin.stat().st_mtime if chemin.exists() else 0.0
        # fallback_mf=True : on OMET la 48 h plutôt que de ne rien écrire si elle échoue.
        code = executer_veille(
            config, secrets=None, now_utc=now_utc, preview_path=str(chemin), fallback_mf=True
        )
        ecrit = chemin.exists() and chemin.stat().st_mtime > avant
        etat = "écrit ✓" if ecrit else "PAS écrit ✗"
        print(f"  {moment:11} (now={now_utc:%Y-%m-%d %H:%MZ}) → code={code} → {etat} ({chemin})")


if __name__ == "__main__":
    main()
