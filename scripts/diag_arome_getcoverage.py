"""Smoke GetCoverage : valide les coverage IDs AROME au point + lève 2 deferrals.

Étape 0 de la phase 1 (ADR-0021) : avant d'écrire `meteofrance_arome.py`, on
confirme par un VRAI GetCoverage que (a) les coverage IDs AROME HD 0.01 répondent
au point de Pleine-Fougères, (b) la valeur de `PRECIPITATION_TYPE_60_MIN` (code
GRIB 4.201 → phase), (c) la valeur de `N_PROBA_PRECI06_1` PE-AROME (proba % de
pluie > 1 mm / 6 h). Réseau + clé DP requis → tourne en CI.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import requests  # noqa: E402
import yaml  # noqa: E402

from meteo_socle.sources.meteofrance_arpege import (  # noqa: E402
    ENV_BASIC,
    _bearer,
    _valeur_point,
)

BASE = "https://public-api.meteofrance.fr/public"
AROME = f"{BASE}/arome/1.0/wcs/MF-NWP-HIGHRES-AROME-001-FRANCE-WCS"
PEAROME = f"{BASE}/pearome/1.0/wcs/MF-NWP-HIGHRES-PEAROME-0025-FRANCE-WCS"
CONFIG = REPO_ROOT / "config" / "veille.yaml"
_TIMEOUT = (10.0, 40.0)


def _coords() -> tuple[float, float]:
    site = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["site"]
    return site["latitude"], site["longitude"]


def _dernier_run(session, token, wcs_base, prefixe) -> str:
    """Suffixe de run le plus récent (``2026-...Z``) pour un préfixe de coverage."""
    resp = session.get(
        f"{wcs_base}/GetCapabilities",
        params={"service": "WCS", "version": "2.0.1", "language": "eng"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=_TIMEOUT,
        verify=False,  # noqa: S501
    )
    runs = re.findall(rf"{re.escape(prefixe)}___(\d{{4}}-\d\d-\d\dT\d\d\.\d\d\.\d\dZ)", resp.text)
    if not runs:
        raise RuntimeError(f"Pas de run pour {prefixe} sur {wcs_base}")
    return sorted(runs)[-1]


def _axe_temps(session, token, wcs_base, cid):
    """Offsets temps (s) d'un coverage via DescribeCoverage."""
    resp = session.get(
        f"{wcs_base}/DescribeCoverage",
        params={"service": "WCS", "version": "2.0.1", "coverageid": cid},
        headers={"Authorization": f"Bearer {token}"},
        timeout=_TIMEOUT,
        verify=False,  # noqa: S501
    )
    for bloc in re.findall(r"<gmlrgrid:coefficients>([0-9 ]+)</gmlrgrid:coefficients>", resp.text):
        vals = [int(x) for x in bloc.split()]
        if vals and max(vals) >= 3600 and all(v % 3600 == 0 for v in vals):
            return vals
    return []


def main() -> None:
    import pandas as pd

    basic = os.environ.get(ENV_BASIC, "")
    if not basic:
        print(f"Clé DP ({ENV_BASIC}) absente → STOP.")
        return
    lat, lon = _coords()
    session = requests.Session()
    token = _bearer(session, basic)
    print(f"Point : {lat}, {lon}\n")

    # --- AROME HD : run récent + échéance ~+24 h ---
    run = _dernier_run(session, token, AROME, "TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND")
    run_ts = pd.Timestamp(run.replace(".", ":").replace("T", " ")[:19] + "+00:00")
    print(f"AROME run = {run}")
    t24 = run_ts + pd.Timedelta(hours=24)

    # (label, suffixe coverage avant ___run, hauteur, accum _PTnH ?)
    cibles = [
        ("T 2m (K)", "TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 2, ""),
        ("HR 2m (%)", "RELATIVE_HUMIDITY__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 2, ""),
        ("Rafale 10m (m/s)", "WIND_SPEED_GUST__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 10, ""),
        ("Nébulosité tot (%)", "TOTAL_CLOUD_COVER__GROUND_OR_WATER_SURFACE", None, ""),
        ("Pluie 1h (mm)", "TOTAL_PRECIPITATION__GROUND_OR_WATER_SURFACE", None, "_PT1H"),
        ("PTYPE_60 (code)", "PRECIPITATION_TYPE_60_MIN__GROUND_OR_WATER_SURFACE", None, ""),
        ("Visi mini 60 (m)", "VISIBILITY_MINI_60MIN__GROUND_OR_WATER_SURFACE", None, ""),
    ]
    print(f"== AROME HD @ +24 h ({t24:%Y-%m-%d %H:%MZ}) ==")
    for label, prefixe, hauteur, accum in cibles:
        cid = f"{prefixe}___{run}{accum}"
        try:
            val = _valeur_point(session, token, cid, t24, lat, lon, hauteur, wcs_base=AROME)
            print(f"  {label:20} = {val}")
        except Exception as e:  # noqa: BLE001
            print(f"  {label:20} = ÉCHEC {type(e).__name__}: {str(e)[:90]}")

    # PTYPE sur quelques échéances (voir la gamme de codes).
    print("\n  PTYPE_60 sur +6/+12/+18/+24/+30 h :")
    cid_pt = f"PRECIPITATION_TYPE_60_MIN__GROUND_OR_WATER_SURFACE___{run}"
    for h in (6, 12, 18, 24, 30):
        t = run_ts + pd.Timedelta(hours=h)
        try:
            v = _valeur_point(session, token, cid_pt, t, lat, lon, None, wcs_base=AROME)
            print(f"    +{h:2}h = {v}")
        except Exception as e:  # noqa: BLE001
            print(f"    +{h:2}h = ÉCHEC {str(e)[:60]}")

    # --- PE-AROME : proba pluie > 1 mm / 6 h ---
    print("\n== PE-AROME N_PROBA_PRECI06_1 (proba pluie >1mm/6h) ==")
    try:
        run_p = _dernier_run(session, token, PEAROME, "N_PROBA_PRECI06_1__GROUND_OR_WATER_SURFACE")
        run_p_ts = pd.Timestamp(run_p.replace(".", ":").replace("T", " ")[:19] + "+00:00")
        cid_p = f"N_PROBA_PRECI06_1__GROUND_OR_WATER_SURFACE___{run_p}"
        offs = _axe_temps(session, token, PEAROME, cid_p)
        hmax = (max(offs) // 3600) if offs else "?"
        print(f"  run = {run_p} ; {len(offs)} échéances ; max +{hmax} h")
        for h in (12, 24, 36):
            t = run_p_ts + pd.Timedelta(hours=h)
            try:
                v = _valeur_point(session, token, cid_p, t, lat, lon, None, wcs_base=PEAROME)
                print(f"    +{h}h = {v} %")
            except Exception as e:  # noqa: BLE001
                print(f"    +{h}h = ÉCHEC {str(e)[:70]}")
    except Exception as e:  # noqa: BLE001
        print(f"  ÉCHEC {type(e).__name__}: {str(e)[:120]}")


if __name__ == "__main__":
    main()
