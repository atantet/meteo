"""Preview hors-ligne du mail Veille **et** du bilan de l'atelier au même instant.

Génère, pour un même ``now_utc`` (donc le **même run ARPEGE 00Z**) :

- le mail Veille du matin (HTML) — sa section « La semaine » utilise ARPEGE 00Z ;
- les figures du bilan hydrique de l'atelier (PNG, plein champ + sous abri),
  calculées par ``apps.atelier_irrigation.calcul`` avec les **paramètres par
  défaut** de l'app — sans lancer Streamlit.

Le mail et l'atelier sont ainsi « reliés » : ils reposent sur exactement la même
prévision et les mêmes défauts, ce qui permet de vérifier leur cohérence d'un
coup d'œil.

Usage :
    python scripts/preview_veille_atelier.py                 # ce matin (05:30 UTC)
    python scripts/preview_veille_atelier.py 2026-06-10T05:30  # instant précis (UTC)
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # rendu fichier, pas d'affichage

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (_REPO_ROOT, _REPO_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pandas as pd  # noqa: E402

from apps.atelier_irrigation import calcul  # noqa: E402
from apps.operationnelle.charts import figure_bilan_sol_complet, figure_bilan_tunnel  # noqa: E402
from apps.operationnelle.config import load_config as load_config_op  # noqa: E402
from apps.veille.__main__ import executer_veille  # noqa: E402
from apps.veille.config import load_config as load_config_veille  # noqa: E402
from apps.veille.config import load_dotenv_if_present  # noqa: E402

OUT = Path("/tmp")


def _now_utc() -> pd.Timestamp:
    if len(sys.argv) > 1:
        return pd.Timestamp(sys.argv[1], tz="UTC")
    # Par défaut : ce matin (créneau matin → le mail inclut la semaine).
    return pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(hours=5, minutes=30)


def main() -> None:
    now_utc = _now_utc()
    load_dotenv_if_present()
    run = calcul.run_00z(now_utc)
    print(f"Instant de référence : {now_utc} (run ARPEGE 00Z = {run:%Y-%m-%d %HZ})")

    # --- Mail Veille (matin) : sa section semaine utilise ARPEGE 00Z ---
    mail = OUT / "veille_preview_matin.html"
    code = executer_veille(load_config_veille(), secrets=None, now_utc=now_utc, preview_path=mail)
    print(f"Mail matin : code={code} -> {mail}")

    # --- Atelier : même run ARPEGE, paramètres par défaut, sans Streamlit ---
    config_op = load_config_op()
    site = config_op["site"]
    horizon = int(config_op["source_meteo"]["horizon_court_jours"])
    prevision = calcul.fetch_arpege_run(
        site["latitude"], site["longitude"], horizon, calcul.run_00z(now_utc)
    )
    quotidien = calcul.quotidien_du_jour(config_op, prevision, now_utc)
    coefficients = calcul.charger_coefficients()
    params = dict(calcul.PARAMS_DEFAUT)
    stade = calcul.stade_defaut(coefficients, params["culture"])
    bilan_pa, bilan_tu = calcul.bilans(quotidien, stade=stade, **params)

    fig_pa = figure_bilan_sol_complet(bilan_pa, apport_max_mm=params["apport_max_mm"])
    pa = OUT / "atelier_bilan_plein_champ.png"
    fig_pa.savefig(pa, dpi=130, bbox_inches="tight")
    fig_tu = figure_bilan_tunnel(bilan_tu, apport_max_mm=params["apport_max_mm"])
    tu = OUT / "atelier_bilan_abri.png"
    fig_tu.savefig(tu, dpi=130, bbox_inches="tight")
    print(f"Atelier (défauts {params['culture']}/{stade}) : {pa} · {tu}")
    print(f"  pluie ARPEGE par jour : {dict(bilan_pa['pluie_mm'].round(2))}")


if __name__ == "__main__":
    main()
