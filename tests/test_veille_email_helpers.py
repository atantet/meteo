"""Tests des helpers de formatage date/heure FR (apps.veille.email).

Critiques car partagés entre App 1 Veille et App 2 Opérationnelle.
"""

from __future__ import annotations

import sys
import zoneinfo
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def test_format_date_fr_jours_et_mois() -> None:
    from apps.veille.email import format_date_fr

    assert format_date_fr(datetime(2026, 5, 28)) == "Jeudi 28 mai 2026"
    assert format_date_fr(datetime(2026, 1, 1)) == "Jeudi 1 janvier 2026"
    assert format_date_fr(datetime(2026, 12, 31)) == "Jeudi 31 décembre 2026"
    # Capitalize off → minuscule.
    assert format_date_fr(datetime(2026, 5, 28), capitalize_jour=False) == "jeudi 28 mai 2026"


def test_format_horodatage_fr_inclut_utc_et_locale() -> None:
    from apps.veille.email import format_horodatage_fr

    dt_utc = datetime(2026, 5, 28, 21, 23, tzinfo=zoneinfo.ZoneInfo("UTC"))
    out = format_horodatage_fr(dt_utc)
    # CEST (UTC+2) en mai pour Europe/Paris.
    assert "21:23 UTC" in out
    assert "23:23 heure locale" in out
    assert "Jeudi 28 mai 2026" in out


def test_format_horodatage_fr_naive_input_traite_comme_utc() -> None:
    """Datetime naïve sans tz → considéré comme UTC pour la sortie."""
    from apps.veille.email import format_horodatage_fr

    dt_naive = datetime(2026, 1, 15, 12, 0)  # janvier = CET (UTC+1)
    out = format_horodatage_fr(dt_naive)
    assert "12:00 UTC" in out
    assert "13:00 heure locale" in out


def test_format_t0_court() -> None:
    from apps.veille.email import format_t0_court

    t0 = pd.Timestamp("2026-05-28 22:00:00+00:00")
    assert format_t0_court(t0) == "22:00 UTC (00:00 heure locale)"


def test_format_t0_court_none() -> None:
    from apps.veille.email import format_t0_court

    assert format_t0_court(None) == "—"


def test_format_t0_court_tz_locale_distincte() -> None:
    from apps.veille.email import format_t0_court

    t0 = pd.Timestamp("2026-05-28 12:00:00+00:00")
    # Europe/Lisbon en été = UTC+1.
    out = format_t0_court(t0, tz_locale="Europe/Lisbon")
    assert "12:00 UTC" in out
    assert "13:00 heure locale" in out
