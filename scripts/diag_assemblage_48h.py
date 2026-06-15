"""Smoke live de la chaîne 48 h assemblée (ADR-0021, porte de validation phase 2).

Exécute ``assembler_prevision_48h`` au point réel avec les derniers runs AROME /
PE-AROME, et imprime un extrait du df assemblé (weather_code + proba + T + pluie),
les tranches de Vigilance orages, et le niveau max. Valide d'un coup AROME +
picto MF + PE-AROME + DPVigilance + overlay orage. Réseau + clé DP → CI.

Horizon réduit à 1 j (le fetch AROME horaire est cadencé par le quota MF/min).
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

import pandas as pd  # noqa: E402
import requests  # noqa: E402
import yaml  # noqa: E402

from apps.veille.prevision_48h import assembler_prevision_48h  # noqa: E402
from meteo_socle.sources.meteofrance_arome import WCS_BASE as AROME_BASE  # noqa: E402
from meteo_socle.sources.meteofrance_arpege import ENV_BASIC, _bearer  # noqa: E402
from meteo_socle.sources.meteofrance_proba_arome import WCS_BASE as PEAROME_BASE  # noqa: E402

CONFIG = REPO_ROOT / "config" / "veille.yaml"


def _site() -> tuple[float, float, str]:
    site = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["site"]
    return site["latitude"], site["longitude"], str(site.get("localisation", "Pleine-Fougères"))


def _dernier_run(session, token, wcs_base, prefixe) -> pd.Timestamp:
    resp = session.get(
        f"{wcs_base}/GetCapabilities",
        params={"service": "WCS", "version": "2.0.1", "language": "eng"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=(10.0, 40.0),
        verify=False,  # noqa: S501
    )
    runs = re.findall(rf"{re.escape(prefixe)}___(\d{{4}}-\d\d-\d\dT\d\d\.\d\d\.\d\dZ)", resp.text)
    if not runs:
        raise RuntimeError(f"Pas de run pour {prefixe}")
    r = sorted(runs)[-1]
    return pd.Timestamp(r.replace(".", ":").replace("T", " ")[:19] + "+00:00")


def main() -> None:
    basic = os.environ.get(ENV_BASIC, "")
    if not basic:
        print(f"Clé DP ({ENV_BASIC}) absente → STOP.")
        return
    lat, lon, position = _site()
    session = requests.Session()
    token = _bearer(session, basic)
    run_arome = _dernier_run(
        session, token, AROME_BASE, "TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND"
    )
    run_proba = _dernier_run(
        session, token, PEAROME_BASE, "N_PROBA_PRECI06_1__GROUND_OR_WATER_SURFACE"
    )
    print(f"run AROME = {run_arome}  |  run PE-AROME = {run_proba}\n")

    prevision, vigilance = assembler_prevision_48h(
        run_arome,
        lat,
        lon,
        departement="35",
        position={"name": position, "timezone": "Europe/Paris"},
        run_proba_utc=run_proba,
        basic=basic,
        session=session,
    )
    df = prevision.df
    cols = [
        "weather_code",
        "probabilite_pluie_pct",
        "temperature_2m",
        "precipitation",
        "type_precip",
    ]
    print(f"df 48 h : {len(df)} lignes, colonnes = {list(df.columns)}\n")
    print(df[cols].head(12).to_string())
    print(f"\nweather_code non nuls : {int(df['weather_code'].notna().sum())}/{len(df)}")
    print(f"proba renseignée : {int(df['probabilite_pluie_pct'].notna().sum())}/{len(df)}")
    print(f"\nVigilance dept 35 : niveau max = {vigilance.niveau_max_global}")
    print(f"tranches orages (≥jaune) : {vigilance.tranches_orages()}")


if __name__ == "__main__":
    main()
