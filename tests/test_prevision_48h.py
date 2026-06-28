"""Test offline de l'assemblage 48 h (cœur pur, sans réseau).

Vérifie : picto dérivé (weather_code), proba diffusée à l'heure, et **overlay
orage** depuis une tranche de Vigilance horodatée (code selon le niveau Vigilance :
jaune→91, orange→92, rouge→93 ; 95 si niveau inconnu).
"""

from __future__ import annotations

import pandas as pd

from apps.veille.prevision_48h import _WMO_ORAGE_PAR_NIVEAU, WMO_ORAGE, assembler_df_48h
from meteo_socle.sources.dpvigilance import TrancheVigilance
from meteo_socle.sources.meteofrance_phealth import UVJournalier, libelle_uv_oms

_CODES_ORAGE = frozenset(_WMO_ORAGE_PAR_NIVEAU.values()) | {WMO_ORAGE}


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
    # 14 h et 15 h dans la tranche orages jaune (niveau=2) → code 91.
    assert df.loc["2026-06-15T14:00:00Z", "weather_code"] == _WMO_ORAGE_PAR_NIVEAU[2]
    assert df.loc["2026-06-15T15:00:00Z", "weather_code"] == _WMO_ORAGE_PAR_NIVEAU[2]
    # 12 h (hors tranche, sec) → picto dérivé, jamais orage.
    assert df.loc["2026-06-15T12:00:00Z", "weather_code"] not in _CODES_ORAGE
    # 16 h hors tranche (borne haute exclue), sec → pas orage.
    assert df.loc["2026-06-15T16:00:00Z", "weather_code"] not in _CODES_ORAGE
    # Proba diffusée (plus proche) : 15 h proche de la valeur 60.
    assert df.loc["2026-06-15T15:00:00Z", "probabilite_pluie_pct"] == 60.0


def test_orage_pas_peint_sur_ciel_degage() -> None:
    """Garde-fou (2026-06-22) : ciel clair dans la fenêtre Vigilance orages → PAS d'orage.

    On se cale sur le picto MF par créneau (MF affiche peu nuageux les heures dégagées
    même Vigilance orages active) ; le risque reste porté par le tableau Vigilance.
    Ciel inconnu (<NA>) → on garde l'orage par prudence.
    """
    idx = pd.date_range("2026-06-15T12:00:00Z", periods=4, freq="h")  # 12..15 UTC
    df_in = pd.DataFrame(
        {
            "cloud_cover": [0.02, 0.02, 0.90, float("nan")],  # clair, clair, couvert, inconnu
            "precipitation": [0.0] * 4,
            "type_precip": [0.0] * 4,
            "visibilite_m": [20000.0] * 4,
            "temperature_2m": [290.0] * 4,
        },
        index=idx,
    )
    tranches = [  # Vigilance orages sur les 4 heures.
        TrancheVigilance(
            pd.Timestamp("2026-06-15T12:00:00Z"), pd.Timestamp("2026-06-15T16:00:00Z"), 2
        )
    ]
    df = assembler_df_48h(df_in, pd.Series(dtype=float), tranches)

    assert df.loc["2026-06-15T12:00:00Z", "weather_code"] not in _CODES_ORAGE  # clair → pas orage
    assert df.loc["2026-06-15T13:00:00Z", "weather_code"] not in _CODES_ORAGE  # clair → pas orage
    wmo_jaune = _WMO_ORAGE_PAR_NIVEAU[2]
    assert df.loc["2026-06-15T14:00:00Z", "weather_code"] == wmo_jaune  # couvert → orage jaune
    assert df.loc["2026-06-15T15:00:00Z", "weather_code"] == wmo_jaune  # inconnu → orage jaune


def test_sans_tranche_aucun_orage() -> None:
    df = assembler_df_48h(_arome_synthetique(), pd.Series(dtype=float), [])
    assert df["weather_code"].apply(lambda c: c not in _CODES_ORAGE).all()
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
    assert prev.df["weather_code"].apply(lambda c: c not in _CODES_ORAGE).all()  # pas d'overlay


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
    assert df.loc["2026-06-15T15:00:00Z", "weather_code"] == _WMO_ORAGE_PAR_NIVEAU[2]


# ---------------------------------------------------------------------------
# Tests PHEALTH UV
# ---------------------------------------------------------------------------


def test_libelle_uv_oms_seuils() -> None:
    assert libelle_uv_oms(0.0) == ("Faible", "#57A032")
    assert libelle_uv_oms(2.0) == ("Faible", "#57A032")
    assert libelle_uv_oms(2.5) == ("Faible", "#57A032")  # round(2.5)=2 (arrondi bancaire)
    assert libelle_uv_oms(2.6) == ("Modéré", "#D4B800")  # round(2.6)=3
    assert libelle_uv_oms(3.0) == ("Modéré", "#D4B800")
    assert libelle_uv_oms(5.0) == ("Modéré", "#D4B800")
    assert libelle_uv_oms(6.0) == ("Élevé", "#E65B00")
    assert libelle_uv_oms(7.0) == ("Élevé", "#E65B00")
    assert libelle_uv_oms(7.5) == ("Très élevé", "#CC0000")  # round(7.5)=8
    assert libelle_uv_oms(8.0) == ("Très élevé", "#CC0000")
    assert libelle_uv_oms(10.0) == ("Très élevé", "#CC0000")
    assert libelle_uv_oms(11.0) == ("Extrême", "#6B49C8")


def test_assembler_tolere_phealth_absent(monkeypatch) -> None:
    """PHEALTH KO → 48 h quand même produite, uv_journalier = None."""
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

    def _vig_down(*a, **k):
        raise p48.VigilanceDPIndisponibleError("down")

    def _uv_down(*a, **k):
        raise p48.PheaithIndisponibleError("down")

    monkeypatch.setattr(p48, "recuperer_vigilance_dp", _vig_down)
    monkeypatch.setattr(p48, "obtenir_uv", _uv_down)

    prev, _ = p48.assembler_prevision_48h(
        pd.Timestamp("2026-06-15T00:00:00Z"), 48.5, -1.6, "35", {"name": "x", "timezone": "UTC"}
    )
    assert prev.uv_journalier is None
    assert "weather_code" in prev.df.columns


def test_assembler_uv_presente(monkeypatch) -> None:
    """PHEALTH OK → uv_journalier attaché à Prevision48h."""
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

    def _vig_down2(*a, **k):
        raise p48.VigilanceDPIndisponibleError("down")

    uv_stub = UVJournalier(uvi_j0=6.0, uvi_j1=4.5, run_utc=pd.Timestamp("2026-06-15T00:00:00Z"))
    monkeypatch.setattr(p48, "recuperer_vigilance_dp", _vig_down2)
    monkeypatch.setattr(p48, "obtenir_uv", lambda *a, **k: uv_stub)

    prev, _ = p48.assembler_prevision_48h(
        pd.Timestamp("2026-06-15T00:00:00Z"), 48.5, -1.6, "35", {"name": "x", "timezone": "UTC"}
    )
    assert prev.uv_journalier is not None
    assert prev.uv_journalier.uvi_j0 == 6.0
    assert prev.uv_journalier.uvi_j1 == 4.5
