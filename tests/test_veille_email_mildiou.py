"""Tests du bloc HTML mildiou Smith dans le mail Veille (cf. ADR-0007)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _indicateurs_avec_mildiou(jours_risque: int, total_jours: int = 3):
    """Construit un IndicateursVeille minimal avec section mildiou peuplée."""
    from apps.veille.indicateurs import IndicateursVeille

    idx = pd.date_range("2026-07-01", periods=total_jours, freq="D")
    detail = pd.DataFrame(
        {
            "t_min_celsius": [12.0] * total_jours,
            "heures_humectation": [15] * total_jours,
            "smith_period": [True] * jours_risque + [False] * (total_jours - jours_risque),
        },
        index=idx,
    )
    jours = list(detail.index[detail["smith_period"]])
    return IndicateursVeille(
        temperature_min_24h_celsius=12.0,
        temperature_max_24h_celsius=22.0,
        cumul_pluie_24h_mm=0.0,
        cumul_pluie_48h_mm=0.0,
        cumul_pluie_72h_mm=0.0,
        vent_max_24h_kmh=15.0,
        rafales_max_24h_kmh=25.0,
        direction_vent_dominante_deg=180.0,
        direction_vent_dominante_cardinal="S",
        etp_jour_mm=4.0,
        bilan_eau_7j_mm=-10.0,
        prob_pluie_max_24h_pct=20.0,
        prob_pluie_max_48h_pct=30.0,
        prob_pluie_max_72h_pct=40.0,
        tension_irrigation=False,
        mildiou_smith_jours_a_risque=jours,
        mildiou_smith_detail=detail,
        prevision_t0_utc=pd.Timestamp("2026-07-01 00:00", tz="UTC"),
    )


def test_bloc_mildiou_smith_avec_periode_detectee() -> None:
    from apps.veille.email import _bloc_mildiou_smith

    ind = _indicateurs_avec_mildiou(jours_risque=2, total_jours=3)
    html = _bloc_mildiou_smith(ind)
    assert "Mildiou tomate" in html
    assert "2 jour(s)" in html
    # Bandeau orange (e67e22) indique un risque.
    assert "#e67e22" in html
    # 3 lignes de données (header a un style ≠ <tr> bare).
    assert html.count("<tr>") == 3


def test_bloc_mildiou_smith_sans_periode() -> None:
    from apps.veille.email import _bloc_mildiou_smith

    ind = _indicateurs_avec_mildiou(jours_risque=0, total_jours=3)
    html = _bloc_mildiou_smith(ind)
    assert "pas de période de Smith" in html
    # Bandeau vert (27ae60) = pas de risque.
    assert "#27ae60" in html


def test_bloc_mildiou_smith_vide_si_indicateur_non_calcule() -> None:
    """Si indicateurs sans détail (mildiou désactivé), bloc retourne vide."""
    from apps.veille.email import _bloc_mildiou_smith
    from apps.veille.indicateurs import IndicateursVeille

    ind = IndicateursVeille(
        temperature_min_24h_celsius=12.0,
        temperature_max_24h_celsius=22.0,
        cumul_pluie_24h_mm=0.0,
        cumul_pluie_48h_mm=0.0,
        cumul_pluie_72h_mm=0.0,
        vent_max_24h_kmh=15.0,
        rafales_max_24h_kmh=25.0,
        direction_vent_dominante_deg=180.0,
        direction_vent_dominante_cardinal="S",
        etp_jour_mm=4.0,
        bilan_eau_7j_mm=-10.0,
        prob_pluie_max_24h_pct=20.0,
        prob_pluie_max_48h_pct=30.0,
        prob_pluie_max_72h_pct=40.0,
        tension_irrigation=False,
        # Pas de détail → bloc doit être vide.
        prevision_t0_utc=pd.Timestamp("2026-07-01 00:00", tz="UTC"),
    )
    assert _bloc_mildiou_smith(ind) == ""
