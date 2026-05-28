"""Formatage de dates et heures en français — partagé entre apps.

Évite la dépendance à ``locale.setlocale("fr_FR.UTF-8")`` (souvent absent
en CI / containers). Centralise les helpers pour ne pas dupliquer entre
App 1 Veille (email), App 2 Opérationnelle (Streamlit), et autres apps
futures.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime

import pandas as pd

JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]  # fmt: skip


def format_date_fr(dt: datetime, capitalize_jour: bool = True) -> str:
    """Formate une date en français : ``Jeudi 28 mai 2026``."""
    j = JOURS_FR[dt.weekday()]
    if capitalize_jour:
        j = j.capitalize()
    return f"{j} {dt.day} {MOIS_FR[dt.month - 1]} {dt.year}"


def format_horodatage_fr(dt_utc: datetime, tz_locale: str = "Europe/Paris") -> str:
    """Formate l'horodatage : ``Jeudi 28 mai 2026, 21:23 UTC (23:23 heure locale)``.

    ``dt_utc`` peut être naïf (alors traité comme UTC) ou tz-aware.
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
    dt_loc = dt_utc.astimezone(zoneinfo.ZoneInfo(tz_locale))
    return (
        f"{format_date_fr(dt_utc)}, "
        f"{dt_utc.strftime('%H:%M')} UTC "
        f"({dt_loc.strftime('%H:%M')} heure locale)"
    )


def format_t0_court(t0_utc: pd.Timestamp | None, tz_locale: str = "Europe/Paris") -> str:
    """``22:00 UTC (00:00 heure locale)`` pour un premier pas de prévision."""
    if t0_utc is None:
        return "—"
    if t0_utc.tzinfo is None:
        t0_utc = t0_utc.tz_localize("UTC")
    t0_loc = t0_utc.tz_convert(tz_locale)
    return f"{t0_utc.strftime('%H:%M')} UTC ({t0_loc.strftime('%H:%M')} heure locale)"
