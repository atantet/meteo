"""Sonde : que contient AROME-direct (WCS Données Publiques) avec la clé DP ?

But précis : savoir si AROME expose la **visibilité** (→ vrai brouillard, au lieu
du proxy HR), et au passage CAPE / nébulosité / un éventuel champ « temps sensible ».
Liste aussi tous les coverages, pour voir ce qu'on a sous la main.

On interroge le ``GetCapabilities`` WCS de plusieurs collections AROME candidates
(le nom exact de la collection varie) avec le Bearer DP. ARPEGE sert de contrôle
(base connue qui marche). Aucune donnée téléchargée, juste les métadonnées.

Lecture :
- 200 + coverages listés → la collection est accessible à ta clé.
- 403 → ta clé n'est **pas abonnée** à cette API (à activer sur le portail).
- 404 → mauvais nom de collection (on en essaie plusieurs).
- VISIBILITY présent → on remplace le proxy HR par la vraie visibilité (48 h).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Bootstrap d'import (cf. autres scripts).
REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import requests  # noqa: E402

from meteo_socle.sources.meteofrance_arpege import ENV_BASIC, _bearer  # noqa: E402

# Collections WCS candidates (public-api). Le nom exact de la collection AROME
# varie (HD 0.01°, 0.025°) ; on essaie plusieurs et on rapporte ce qui répond.
BASE = "https://public-api.meteofrance.fr/public"
COLLECTIONS: list[tuple[str, str]] = [
    ("ARPEGE 0.25 (contrôle)", f"{BASE}/arpege/1.0/wcs/MF-NWP-GLOBAL-ARPEGE-025-GLOBE-WCS"),
    ("AROME HD 0.01", f"{BASE}/arome/1.0/wcs/MF-NWP-HIGHRES-AROME-001-FRANCE-WCS"),
    ("AROME 0.025", f"{BASE}/arome/1.0/wcs/MF-NWP-HIGHRES-AROME-0025-FRANCE-WCS"),
    ("AROME-PI 0.01", f"{BASE}/aromepi/1.0/wcs/MF-NWP-HIGHRES-AROMEPI-001-FRANCE-WCS"),
    ("AROME-EPS", f"{BASE}/arome-eps/1.0/wcs/MF-NWP-HIGHRES-AROME-EPS-0025-FRANCE-WCS"),
]

# Familles de paramètres qui nous intéressent (recherche insensible à la casse).
INTERETS = ("VISIBILITY", "CAPE", "CLOUD", "NEBUL", "WEATHER", "WW", "PRECIP", "HUMIDITY")
_TIMEOUT = (10.0, 30.0)


def _coverages(xml: str) -> list[str]:
    """Extrait les CoverageId du GetCapabilities (sans dépendance XML)."""
    ids = re.findall(r"<(?:\w+:)?CoverageId>([^<]+)</(?:\w+:)?CoverageId>", xml)
    return sorted(set(ids))


def _prefixes(ids: list[str]) -> list[str]:
    """Préfixe paramètre (avant le premier ``__``) de chaque coverage."""
    return sorted({cid.split("__", 1)[0] for cid in ids})


def main() -> None:
    basic = os.environ.get(ENV_BASIC, "")
    if not basic:
        print(f"Clé DP ({ENV_BASIC}) absente → impossible de sonder. STOP.")
        return
    session = requests.Session()
    bearer = _bearer(session, basic)
    print("Bearer DP : OK\n")

    for label, base in COLLECTIONS:
        try:
            resp = session.get(
                f"{base}/GetCapabilities",
                params={"service": "WCS", "version": "2.0.1"},
                headers={"Authorization": f"Bearer {bearer}"},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            print(f"== {label} ==\n  ÉCHEC réseau : {type(e).__name__}: {e}\n")
            continue
        print(f"== {label} ==  (HTTP {resp.status_code})")
        if resp.status_code != 200:
            print(f"  {resp.text[:200]!r}\n")
            continue
        ids = _coverages(resp.text)
        prefixes = _prefixes(ids)
        print(f"  {len(ids)} coverages, {len(prefixes)} familles de paramètres.")
        for motif in INTERETS:
            hits = [p for p in prefixes if motif in p.upper()]
            tag = ", ".join(hits) if hits else "—"
            print(f"    {motif:<10}: {tag}")
        print()


if __name__ == "__main__":
    main()
