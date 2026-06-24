#!/usr/bin/env python
"""Fetche la prévision officielle MF et auto-labellise labels.csv.

À lancer dans les 30 minutes suivant un run Veille (matin ~05:00 UTC,
après-midi ~17:00 UTC). Le webservice ``webservice.meteofrance.com`` est
accessible en local seulement — bloqué depuis les runners GH Actions.

Usage
-----
    python calibration/fetch_labels.py
    python calibration/fetch_labels.py --run-id 28113733569 --horizon 48
    python calibration/fetch_labels.py --dry-run   # affiche sans écrire

Le script :

1. Fetche la prévision JSON MF pour les coordonnées config.
2. Mappe les échéances en tranches locales (Nuit/Matin/Après-midi/Soir).
3. Calcule le code WMO dominant par tranche (``desc_vers_wmo`` + agrégation).
4. Récupère automatiquement le ``run_id`` du dernier run Veille (GH Actions).
5. Déduplique et appende dans ``data/calibration/labels.csv``.

Crontab locale recommandée (UTC, après chaque Veille)
------------------------------------------------------
    10 5  * * * TZ=UTC .../calibration/run_pipeline.sh >> /tmp/calib.log 2>&1
    10 17 * * * TZ=UTC .../calibration/run_pipeline.sh >> /tmp/calib.log 2>&1
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

_LAT = 48.543648
_LON = -1.611515
_TOKEN_ENV = "METEOFRANCE_WS_TOKEN"
# Token mobile public (hors licence Etalab — usage calibration locale uniquement).
_TOKEN_DEFAULT = "__Wj7dVSTjV9YGu1guveLyDq0g7S7TfTjaHBTPTpO0kj8__"  # noqa: S105
_WS_URL = "https://webservice.meteofrance.com/forecast"
_LABELS_CSV = Path("data/calibration/labels.csv")
_REPO = "atantet/meteo"
_TZ_LOCAL = ZoneInfo("Europe/Paris")

_FENETRES = [
    ("Nuit", 0, 6),
    ("Matin", 6, 12),
    ("Après-midi", 12, 18),
    ("Soir", 18, 24),
]


# ---------------------------------------------------------------------------
# Classification libellé MF → code OMM
# (copie inline de meteofrance_officiel.desc_vers_wmo, supprimé en ADR-0021)
# ---------------------------------------------------------------------------


def _norm(desc: str) -> str:
    sans = "".join(c for c in unicodedata.normalize("NFD", desc) if unicodedata.category(c) != "Mn")
    return sans.lower().strip()


def _desc_vers_wmo(desc: str) -> int | None:
    d = _norm(desc)
    if not d:
        return None
    if "orage" in d:
        return 96 if "grele" in d else 95
    if "grele" in d:
        return 96
    forte = "fort" in d or "violent" in d
    faible = "faible" in d
    moderee = "moderr" in d or "modere" in d
    averse = "averse" in d
    neige = "neige" in d or "flocon" in d
    if neige and "pluie" in d:
        return 67 if forte else 66
    if neige:
        if averse:
            return 86 if forte else 85
        if forte:
            return 75
        if moderee:
            return 73
        return 71
    if "verglac" in d or "verglas" in d:
        return 67 if forte else 66
    if "bruine" in d and not (moderee or forte):
        return 51
    if averse:
        if forte:
            return 82
        if faible:
            return 80
        return 81
    if "pluie" in d:
        if forte:
            return 65
        if faible:
            return 61
        return 63
    if "brouillard" in d or "brume" in d:
        return 48 if "givrant" in d else 45
    if "tres nuageux" in d or "couvert" in d:
        return 3
    if "peu nuageux" in d:
        return 1
    if any(k in d for k in ("nuageux", "voile", "eclaircie", "variable")):
        return 2
    if any(k in d for k in ("ensoleille", "soleil", "clair")):
        return 0
    return None


# ---------------------------------------------------------------------------
# Agrégation sur fenêtre 6 h
# ---------------------------------------------------------------------------


def _dominant(codes: list[int]) -> int | None:
    if not codes:
        return None
    maxcode = max(codes)
    if maxcode >= 45:
        # Phénomène significatif (pluie, brouillard, orage) → sévérité max
        return maxcode
    # Ciel sec → représentatif (moyenne arrondie, cohérent avec le moteur)
    return int(sum(codes) / len(codes) + 0.5)


def _tranche(hour: int) -> str | None:
    for nom, h0, h1 in _FENETRES:
        if h0 <= hour < h1:
            return nom
    return None


# ---------------------------------------------------------------------------
# Fetch webservice MF
# ---------------------------------------------------------------------------


def _fetch_forecast(lat: float, lon: float, token: str) -> list[dict]:
    resp = requests.get(
        _WS_URL,
        params={"lat": str(lat), "lon": str(lon), "token": token},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    # Le payload peut avoir la liste sous "properties.forecast" ou directement.
    props = data.get("properties") or data
    return list(props.get("forecast", []))


# ---------------------------------------------------------------------------
# GH Actions : dernier run Veille
# ---------------------------------------------------------------------------


def _latest_run_id() -> int | None:
    try:
        out = subprocess.check_output(
            [
                "gh",
                "run",
                "list",
                "--workflow=veille.yaml",
                "--limit=1",
                "--json=databaseId",
                "--jq=.[0].databaseId",
            ],
            text=True,
        )
        return int(out.strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


# ---------------------------------------------------------------------------
# labels.csv
# ---------------------------------------------------------------------------


def _existing_keys(path: Path) -> set[tuple]:
    if not path.exists():
        return set()
    keys: set[tuple] = set()
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            keys.add((int(row["run_id"]), row["jour_local"], row["fenetre"]))
    return keys


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(horizon_h: int = 48, run_id: int | None = None, dry_run: bool = False) -> None:
    token = os.environ.get(_TOKEN_ENV, _TOKEN_DEFAULT)

    try:
        entries = _fetch_forecast(_LAT, _LON, token)
    except requests.RequestException as exc:
        print(f"Webservice MF inaccessible : {exc}")
        return

    if not entries:
        print("Forecast vide — webservice MF indisponible ?")
        return

    now_utc = datetime.now(UTC)
    cutoff = now_utc + timedelta(hours=horizon_h)

    # Grouper par (jour_local, tranche) → liste de codes WMO
    by_tranche: dict[tuple[str, str], list[int]] = {}
    unknown_descs: set[str] = set()
    for e in entries:
        dt_val = e.get("dt")
        if dt_val is None:
            continue
        ts = datetime.fromtimestamp(int(dt_val), tz=UTC)
        if ts < now_utc or ts >= cutoff:
            continue
        desc = (e.get("weather") or {}).get("desc") or ""
        code = _desc_vers_wmo(desc)
        if code is None:
            if desc:
                unknown_descs.add(desc)
            continue
        ts_loc = ts.astimezone(_TZ_LOCAL)
        jour = ts_loc.strftime("%Y-%m-%d")
        tranche = _tranche(ts_loc.hour)
        if tranche is None:
            continue
        by_tranche.setdefault((jour, tranche), []).append(code)

    if unknown_descs:
        print(f"Libellés MF non reconnus (picto omis) : {sorted(unknown_descs)}")

    if run_id is None:
        run_id = _latest_run_id()
    if run_id is None:
        print("run_id introuvable — passer --run-id manuellement.")
        return

    existing = _existing_keys(_LABELS_CSV)
    nouvelles: list[dict] = []

    for (jour, fenetre), codes in sorted(by_tranche.items()):
        key = (run_id, jour, fenetre)
        if key in existing:
            continue
        dom = _dominant(codes)
        if dom is None:
            continue
        nouvelles.append(
            {
                "run_id": run_id,
                "jour_local": jour,
                "fenetre": fenetre,
                "mf_wmo": dom,
                "note": f"auto (ws MF, n={len(codes)})",
            }
        )
        print(f"  + {jour} {fenetre:12s} → WMO {dom}  ({len(codes)} pts)")

    if not nouvelles:
        print(
            f"run {run_id} — rien de nouveau ({len(by_tranche)} tranches, toutes déjà présentes)."
        )
        return

    if dry_run:
        print(f"[dry-run] {len(nouvelles)} lignes non écrites.")
        return

    write_header = not _LABELS_CSV.exists()
    _LABELS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with _LABELS_CSV.open("a", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["run_id", "jour_local", "fenetre", "mf_wmo", "note"],
        )
        if write_header:
            writer.writeheader()
        writer.writerows(nouvelles)
    print(f"✓ {len(nouvelles)} lignes ajoutées → {_LABELS_CSV}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--run-id", type=int, default=None, help="run_id GH Actions (défaut : auto)")
    ap.add_argument("--horizon", type=int, default=48, help="Heures à couvrir (défaut : 48)")
    ap.add_argument("--dry-run", action="store_true", help="Affiche sans écrire")
    args = ap.parse_args()
    main(horizon_h=args.horizon, run_id=args.run_id, dry_run=args.dry_run)
