#!/usr/bin/env python
"""Collecte les logs GH Actions (HORA-DIAG + PICTO-DIAG) et joint aux labels.

Usage
-----
    python calibration/collect.py
    python calibration/collect.py --labels data/calibration/labels.csv \\
                                  --output  data/calibration/dataset.csv

Produit ``data/calibration/dataset.csv`` : une ligne par tranche labelisée,
avec les features AROME agrégées (moyennes sur la fenêtre 6 h) et les
listes horaires (JSON) pour rejouer la règle dans ``optimize.py``.

Sources
-------
- **HORA-DIAG** (nouveau, >= commit 3d6d77b) : une ligne JSON par heure,
  tous les champs AROME (cc, cc_low, cc_mid, precip, temp_c, ptype, visi_m,
  humi, wmo). Utilisé si disponible.
- **PICTO-DIAG** (rétrocompatibilité) : agrégats par tranche (moy/max %),
  pas de temp/ptype/visi. Utilisé en fallback si pas de HORA-DIAG.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = "atantet/meteo"
_LABELS_DEFAULT = Path("data/calibration/labels.csv")
_DATASET_DEFAULT = Path("data/calibration/dataset.csv")

# Regex HORA-DIAG : "... HORA-DIAG 2026-06-24T16:00Z {...}"
_RE_HORA = re.compile(r"HORA-DIAG (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z) (\{[^\n]+\})")

# Regex PICTO-DIAG (fallback anciens runs) :
# "PICTO-DIAG mer. 24/06 Matin | nébul tot 57/91 bas 0/0 moy 0/0 ... | pluie 0.0 mm | codes [...]"
_RE_PICTO = re.compile(
    r"PICTO-DIAG \S+\. (\d{2})/(\d{2})\s+([\w-]+(?:-[\w]+)?)\s*\|"
    r"\s*nébul tot (\d+)/(\d+) bas (\d+)/(\d+) moy (\d+)/(\d+).*?"
    r"\|\s*pluie\s+([\d.]+) mm\s*\|\s*codes\s+\[([^\]]*)\]"
)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _job_id(run_id: int) -> int:
    out = subprocess.check_output(
        ["gh", "run", "view", str(run_id), "--json", "jobs", "--jq", ".jobs[].databaseId"],
        text=True,
    )
    return int(out.strip())


def _fetch_log(job_id: int) -> str:
    return subprocess.check_output(
        ["gh", "api", f"repos/{REPO}/actions/jobs/{job_id}/logs"],
        text=True,
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _year_from_log(log: str) -> int:
    m = re.search(r"(\d{4})-\d{2}-\d{2}T", log)
    return int(m.group(1)) if m else 2026


def _parse_hora(log: str) -> list[dict]:
    rows = []
    for m in _RE_HORA.finditer(log):
        ts_utc, payload = m.group(1), m.group(2)
        try:
            rec = json.loads(payload)
            rec["ts_utc"] = ts_utc
            rows.append(rec)
        except json.JSONDecodeError:
            pass
    return rows


def _parse_picto(log: str, year: int) -> list[dict]:
    rows = []
    for m in _RE_PICTO.finditer(log):
        day, month = int(m.group(1)), int(m.group(2))
        fenetre = m.group(3).strip()
        codes_str = m.group(11).strip()
        codes = [int(c.strip()) for c in codes_str.split(",") if c.strip()]
        rows.append(
            {
                "jour": f"{year}-{month:02d}-{day:02d}",
                "tranche": fenetre,
                "cc_avg": float(m.group(4)),
                "cc_max": float(m.group(5)),
                "cc_low_avg": float(m.group(6)),
                "cc_mid_avg": float(m.group(8)),
                "precip_sum": float(m.group(10)),
                "wmo_codes": codes,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Agrégation horaire → tranche
# ---------------------------------------------------------------------------


def _mean(vals: list) -> float | None:
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 2) if v else None


def _nonnull_max(vals: list) -> float | None:
    v = [x for x in vals if x is not None]
    return round(max(v), 2) if v else None


def _nonnull_min(vals: list) -> float | None:
    v = [x for x in vals if x is not None]
    return round(min(v), 2) if v else None


def _hora_to_tranche(hours: list[dict]) -> dict:
    return {
        "cc_avg": _mean([h.get("cc") for h in hours]),
        "cc_max": _nonnull_max([h.get("cc") for h in hours]),
        "cc_low_avg": _mean([h.get("cc_low") for h in hours]),
        "cc_mid_avg": _mean([h.get("cc_mid") for h in hours]),
        "precip_sum": _mean([h.get("precip") for h in hours]),  # somme approx (1 h each)
        "temp_c_avg": _mean([h.get("temp_c") for h in hours]),
        "visi_m_min": _nonnull_min([h.get("visi_m") for h in hours]),
        "humi_avg": _mean([h.get("humi") for h in hours]),
        # Listes horaires JSON pour rejouer la règle dans optimize.py
        "cc_hours": json.dumps([h.get("cc") for h in hours]),
        "cc_low_hours": json.dumps([h.get("cc_low") for h in hours]),
        "cc_mid_hours": json.dumps([h.get("cc_mid") for h in hours]),
        "precip_hours": json.dumps([h.get("precip") for h in hours]),
        "temp_c_hours": json.dumps([h.get("temp_c") for h in hours]),
        "wmo_hours": json.dumps([h.get("wmo") for h in hours]),
        "source": "hora_diag",
    }


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def build_dataset(labels_csv: Path, output_csv: Path) -> pd.DataFrame:
    labels = pd.read_csv(labels_csv, dtype={"run_id": int, "mf_wmo": int})
    rows: list[dict] = []

    for run_id in labels["run_id"].unique():
        print(f"Fetching run {run_id}…", file=sys.stderr)
        try:
            job_id = _job_id(run_id)
            log = _fetch_log(job_id)
        except subprocess.CalledProcessError as e:
            print(f"  Erreur GH: {e}", file=sys.stderr)
            continue

        year = _year_from_log(log)
        hora_all = _parse_hora(log)
        picto_all = _parse_picto(log, year)
        has_hora = bool(hora_all)

        run_labels = labels[labels["run_id"] == run_id]
        for _, lbl in run_labels.iterrows():
            jour = lbl["jour_local"]
            fenetre = lbl["fenetre"]
            base = {
                "run_id": run_id,
                "jour_local": jour,
                "fenetre": fenetre,
                "mf_wmo": int(lbl["mf_wmo"]),
            }

            if has_hora:
                hours = [
                    h for h in hora_all if h.get("jour") == jour and h.get("tranche") == fenetre
                ]
                if not hours:
                    print(f"  Pas de HORA-DIAG pour {jour} {fenetre}", file=sys.stderr)
                    continue
                rows.append({**base, **_hora_to_tranche(hours)})

            else:
                # Fallback PICTO-DIAG
                prow = next(
                    (p for p in picto_all if p["jour"] == jour and p["tranche"] == fenetre),
                    None,
                )
                if prow is None:
                    print(f"  Pas de PICTO-DIAG pour {jour} {fenetre}", file=sys.stderr)
                    continue
                rows.append(
                    {
                        **base,
                        "cc_avg": prow["cc_avg"],
                        "cc_max": prow["cc_max"],
                        "cc_low_avg": prow["cc_low_avg"],
                        "cc_mid_avg": prow["cc_mid_avg"],
                        "precip_sum": prow["precip_sum"],
                        "temp_c_avg": None,
                        "visi_m_min": None,
                        "humi_avg": None,
                        "cc_hours": None,
                        "cc_low_hours": None,
                        "cc_mid_hours": None,
                        "precip_hours": None,
                        "temp_c_hours": None,
                        "wmo_hours": json.dumps(prow["wmo_codes"]),
                        "source": "picto_diag",
                    }
                )

    df = pd.DataFrame(rows)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"Dataset: {len(df)} lignes → {output_csv}", file=sys.stderr)
    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels", default=_LABELS_DEFAULT, type=Path)
    ap.add_argument("--output", default=_DATASET_DEFAULT, type=Path)
    args = ap.parse_args()
    build_dataset(args.labels, args.output)
