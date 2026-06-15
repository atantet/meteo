"""Sonde : DPVigilance (périodes horodatées) + découverte de la route AROME-EPS.

DPVigilance (`portail-api`, clé DP) : confirme que la clé y accède et que le
produit « carte » expose des **périodes J/J+1 horodatées par phénomène** (→ picto
orage branché sur la Vigilance, compatible matin/après-midi, robuste au blocage
webservice). On inspecte la STRUCTURE du JSON (clés, nb de périodes, timing orages
dept 35), sans tout déverser.

AROME-EPS : on essaie plusieurs chemins WCS candidats (le nom de collection n'est
pas documenté clairement) et on rapporte le statut de chacun.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import requests  # noqa: E402

from meteo_socle.sources.meteofrance_arpege import ENV_BASIC, _bearer  # noqa: E402

DPVIGILANCE_URL = "https://public-api.meteofrance.fr/public/DPVigilance/v1/cartevigilance/encours"
BASE = "https://public-api.meteofrance.fr/public"
# Chemins exacts d'après le client MAIF/meteole (contexte + préfixe collection).
EPS_CANDIDATS: list[str] = [
    f"{BASE}/pearome/1.0/wcs/MF-NWP-HIGHRES-PEAROME-0025-FRANCE-WCS",
    f"{BASE}/pearpege/1.0/wcs/MF-NWP-GLOBAL-PEARP-01-EUROPE-WCS",
    f"{BASE}/pearpege/1.0/wcs/MF-NWP-GLOBAL-PEARP-025-GLOBE-WCS",
    f"{BASE}/pe-arpege/1.0/wcs/MF-NWP-GLOBAL-PEARP-01-EUROPE-WCS",
    f"{BASE}/pe-arpege/1.0/wcs/MF-NWP-GLOBAL-PEARP-025-GLOBE-WCS",
]
_TIMEOUT = (10.0, 30.0)
DEPT = "35"
ORAGES_ID = "3"


def _resume_structure(obj: object, prof: int = 0, max_prof: int = 2) -> str:
    """Aperçu peu profond de la structure JSON (clés / longueurs)."""
    pad = "  " * prof
    if isinstance(obj, dict):
        if prof >= max_prof:
            return f"{{{', '.join(list(obj)[:8])}}}"
        return "\n".join(
            f"{pad}{k}: {_resume_structure(v, prof + 1, max_prof)}"
            for k, v in list(obj.items())[:12]
        )
    if isinstance(obj, list):
        n = len(obj)
        tete = _resume_structure(obj[0], prof + 1, max_prof) if obj else "—"
        return f"[{n}] ex: {tete}"
    s = str(obj)
    return s[:60]


def _sonde_dpvigilance(session: requests.Session, bearer: str) -> None:
    print("== DPVigilance (carte/encours) ==")
    try:
        resp = session.get(
            DPVIGILANCE_URL,
            headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        print(f"  ÉCHEC réseau : {type(e).__name__}: {e}\n")
        return
    print(f"  HTTP {resp.status_code} ({len(resp.content)} o)")
    if resp.status_code != 200:
        print(f"  {resp.text[:200]!r}\n")
        return
    try:
        data = resp.json()
    except ValueError:
        print(f"  Pas du JSON : {resp.text[:160]!r}\n")
        return
    print("  Structure (2 niveaux) :")
    print(_resume_structure(data, prof=2))
    # Cherche les périodes et le timing orages pour le dept 35.
    txt = json.dumps(data, ensure_ascii=False)
    print(f"\n  'periods' présent : {'periods' in txt}")
    print(f"  'timelaps' présent : {'timelaps' in txt}")
    print(f"  dept {DEPT} cité : {bool(re.search(rf'\"{DEPT}\"', txt))}")
    print(f"  phénomène orages (id {ORAGES_ID}) cité : {ORAGES_ID in txt}")
    print()


def _sonde_eps(session: requests.Session, bearer: str) -> None:
    print("== AROME-EPS (découverte de route) ==")
    for base in EPS_CANDIDATS:
        court = base.split("/wcs/", 1)[-1]
        try:
            resp = session.get(
                f"{base}/GetCapabilities",
                params={"service": "WCS", "version": "2.0.1"},
                headers={"Authorization": f"Bearer {bearer}"},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            print(f"  {court}\n    ÉCHEC {type(e).__name__}")
            continue
        if not resp.ok:
            print(f"  [{resp.status_code}] {court} — {resp.text[:400]!r}")
            continue
        ids = re.findall(r"<(?:\w+:)?CoverageId>([^<]+)</(?:\w+:)?CoverageId>", resp.text)
        prefixes = sorted({cid.split("__", 1)[0] for cid in ids})
        print(f"  [{resp.status_code}] {court} — {len(ids)} coverages, {len(prefixes)} familles")
        print(f"        familles: {', '.join(prefixes)}")
    print()


def main() -> None:
    basic = os.environ.get(ENV_BASIC, "")
    if not basic:
        print(f"Clé DP ({ENV_BASIC}) absente → STOP.")
        return
    session = requests.Session()
    bearer = _bearer(session, basic)
    print("Bearer DP : OK\n")
    _sonde_dpvigilance(session, bearer)
    _sonde_eps(session, bearer)


if __name__ == "__main__":
    main()
