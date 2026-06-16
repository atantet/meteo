"""Test offline de l'assemblage 48 h (cœur pur, sans réseau).

Vérifie : picto dérivé (weather_code), proba diffusée à l'heure, et **overlay
orage** depuis une tranche de Vigilance horodatée (→ code 95 sur les heures
couvertes, sinon picto dérivé sans orage).
"""

from __future__ import annotations

import pandas as pd

from apps.veille.prevision_48h import WMO_ORAGE, assembler_df_48h
from meteo_socle.sources.dpvigilance import TrancheVigilance


def _arome_synthetique() -> pd.DataFrame:
    idx = pd.date_range("2026-06-15T12:00:00Z", periods=6, freq="h")  # 12..17 UTC
    return pd.DataFrame(
        {
            "cloud_cover": [0.9] * 6,
            "precipitation": [0.0, 0.0, 2.0, 2.0, 0.0, 0.0],
            "type_precip": [0.0, 0.0, 1.0, 1.0, 0.0, 0.0],  # pluie quand il pleut
            "visibilite_m": [20000.0] * 6,
            "temperature_2m": [290.0] * 6,
        },
        index=idx,
    )


def test_overlay_orage_sur_tranche() -> None:
    df_in = _arome_synthetique()
    proba = pd.Series(
        [10.0, 60.0],
        index=pd.to_datetime(["2026-06-15T12:00Z", "2026-06-15T15:00Z"]),
        name="probabilite_pluie_pct",
    )
    # Vigilance orages 14-16 h (jaune).
    tranches = [
        TrancheVigilance(
            pd.Timestamp("2026-06-15T14:00:00Z"), pd.Timestamp("2026-06-15T16:00:00Z"), 2
        )
    ]
    df = assembler_df_48h(df_in, proba, tranches)

    assert "weather_code" in df.columns and "probabilite_pluie_pct" in df.columns
    # 14 h et 15 h dans la tranche orages → code 95.
    assert df.loc["2026-06-15T14:00:00Z", "weather_code"] == WMO_ORAGE
    assert df.loc["2026-06-15T15:00:00Z", "weather_code"] == WMO_ORAGE
    # 12 h (hors tranche, sec) → picto dérivé, jamais orage.
    assert df.loc["2026-06-15T12:00:00Z", "weather_code"] != WMO_ORAGE
    # 16 h hors tranche (borne haute exclue), sec → pas orage.
    assert df.loc["2026-06-15T16:00:00Z", "weather_code"] != WMO_ORAGE
    # Proba diffusée (plus proche) : 15 h proche de la valeur 60.
    assert df.loc["2026-06-15T15:00:00Z", "probabilite_pluie_pct"] == 60.0


def test_sans_tranche_aucun_orage() -> None:
    df = assembler_df_48h(_arome_synthetique(), pd.Series(dtype=float), [])
    assert (df["weather_code"] != WMO_ORAGE).all()
    assert df["probabilite_pluie_pct"].isna().all()  # proba vide → NaN


def test_assembler_tolere_vigilance_absente(monkeypatch) -> None:
    """DPVigilance KO → 48 h quand même produite (sans overlay orage), Vigilance None."""
    import apps.veille.prevision_48h as p48

    idx = pd.date_range("2026-06-15T00:00:00Z", periods=4, freq="h")
    arome = pd.DataFrame(
        {"cloud_cover": [0.5] * 4, "precipitation": [0.0] * 4, "temperature_2m": [290.0] * 4},
        index=idx,
    )
    monkeypatch.setattr(p48.MeteoFranceArome, "obtenir_run", lambda self, *a, **k: arome)
    monkeypatch.setattr(
        p48.MeteoFranceProbaArome, "obtenir_proba", lambda self, *a, **k: pd.Series(dtype=float)
    )

    def _down(*a, **k):
        raise p48.VigilanceDPIndisponibleError("down")

    monkeypatch.setattr(p48, "recuperer_vigilance_dp", _down)
    prev, vig = p48.assembler_prevision_48h(
        pd.Timestamp("2026-06-15T00:00:00Z"), 48.5, -1.6, "35", {"name": "x", "timezone": "UTC"}
    )
    assert vig is None  # Vigilance tolérée
    assert "weather_code" in prev.df.columns  # 48 h produite
    assert (prev.df["weather_code"] != WMO_ORAGE).all()  # pas d'overlay (pas de tranches)


def test_overlay_orage_l_emporte_sur_picto_absent() -> None:
    """L'overlay orage pose 95 même là où le picto dérivé serait <NA> (ciel manquant)."""
    df_in = _arome_synthetique()
    df_in.loc["2026-06-15T15:00:00Z", "cloud_cover"] = float("nan")  # picto → <NA>
    tranches = [
        TrancheVigilance(
            pd.Timestamp("2026-06-15T14:00:00Z"), pd.Timestamp("2026-06-15T16:00:00Z"), 2
        )
    ]
    df = assembler_df_48h(df_in, pd.Series(dtype=float), tranches)
    assert df.loc["2026-06-15T15:00:00Z", "weather_code"] == WMO_ORAGE
