"""Tests `meteo_socle.indices.mildiou` — Smith periods (cf. ADR-0007)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from meteo_socle.indices.mildiou import (
    agreger_critere_journalier,
    nb_smith_periods_par_annee,
    smith_periods,
)


def _serie_horaire_synth(
    start: str,
    n_jours: int,
    t_celsius_template: list[float],
    hr_template: list[float],
    tz: str = "UTC",
) -> pd.DataFrame:
    """Construit une série horaire (24 h × n_jours) tilée depuis 1 jour-type."""
    assert len(t_celsius_template) == 24
    assert len(hr_template) == 24
    idx = pd.date_range(start, periods=24 * n_jours, freq="h", tz=tz)
    t = np.tile(t_celsius_template, n_jours)
    hr = np.tile(hr_template, n_jours)
    return pd.DataFrame(
        {"temperature_2m": t + 273.15, "humidite_relative": hr},
        index=idx,
    )


def test_agreger_critere_journalier_compte_heures_correctement() -> None:
    # 12 h HR=0.95, 12 h HR=0.50 → 12 h "hautes" / jour.
    df = _serie_horaire_synth(
        "2023-06-15 00:00",
        n_jours=3,
        t_celsius_template=[12.0] * 24,
        hr_template=[0.95] * 12 + [0.50] * 12,
    )
    quot = agreger_critere_journalier(df, tz_locale="UTC")
    assert (quot["heures_humectation"] == 12).all()
    assert quot["t_min_celsius"].tolist() == pytest.approx([12.0, 12.0, 12.0])


def test_agreger_critere_journalier_local_tz_decoupage() -> None:
    """Les heures hautes sont comptées sur jour local, pas UTC."""
    # 24 h consécutives HR=0.95 démarrant à 22:00 UTC le 14 juin
    # → 02:00 UTC le 16 juin. En Europe/Paris (été UTC+2) ça démarre
    # 00:00 le 15. Donc 24 h "hautes" tombent toutes sur 2026-06-15.
    df = _serie_horaire_synth(
        "2026-06-14 22:00",
        n_jours=2,
        t_celsius_template=[12.0] * 24,
        hr_template=[0.95] * 24,
    )
    quot = agreger_critere_journalier(df, tz_locale="Europe/Paris")
    # On attend 24 h "hautes" le 15 juin (la fenêtre entière) en local.
    assert int(quot.loc["2026-06-15", "heures_humectation"]) == 24


def test_smith_periods_detection_canonique() -> None:
    # 2 jours qualifiants consécutifs → flag sur le second.
    quot = pd.DataFrame(
        {
            "t_min_celsius": [12.0, 12.0, 8.0],
            "heures_humectation": [15, 15, 5],
        },
        index=pd.to_datetime(["2023-06-14", "2023-06-15", "2023-06-16"]),
    )
    smith = smith_periods(quot)
    assert smith.tolist() == [False, True, False]


def test_smith_periods_t_min_sous_seuil_invalide() -> None:
    # T_min < 10 °C sur jour A → pas de Smith period sur B.
    quot = pd.DataFrame(
        {
            "t_min_celsius": [9.0, 12.0],
            "heures_humectation": [15, 15],
        },
        index=pd.to_datetime(["2023-06-14", "2023-06-15"]),
    )
    smith = smith_periods(quot)
    assert smith.tolist() == [False, False]


def test_smith_periods_heures_sous_seuil_invalide() -> None:
    # Seulement 10 h HR ≥ 90 % → ne qualifie pas (seuil 11).
    quot = pd.DataFrame(
        {
            "t_min_celsius": [12.0, 12.0],
            "heures_humectation": [15, 10],
        },
        index=pd.to_datetime(["2023-06-14", "2023-06-15"]),
    )
    smith = smith_periods(quot)
    assert smith.tolist() == [False, False]


def test_smith_periods_seuils_personnalisables() -> None:
    quot = pd.DataFrame(
        {
            "t_min_celsius": [8.0, 8.0],
            "heures_humectation": [9, 9],
        },
        index=pd.to_datetime(["2023-06-14", "2023-06-15"]),
    )
    # Smith historique : ne qualifie pas.
    assert not smith_periods(quot).any()
    # Seuils relâchés : qualifie sur jour B.
    smith2 = smith_periods(quot, t_min_celsius=7.0, heures_min=8)
    assert smith2.tolist() == [False, True]


def test_nb_smith_periods_par_annee_compte_correctement() -> None:
    smith = pd.Series(
        [True, False, True, True, False],
        index=pd.to_datetime(
            ["2023-06-15", "2023-07-10", "2024-08-05", "2024-08-06", "2024-09-01"]
        ),
    )
    nb = nb_smith_periods_par_annee(smith)
    assert nb[2023] == 1
    assert nb[2024] == 2


def test_nb_smith_periods_serie_vide_renvoie_serie_vide() -> None:
    smith = pd.Series([], dtype=bool)
    nb = nb_smith_periods_par_annee(smith)
    assert nb.empty


def test_agreger_horaire_serie_vide() -> None:
    df = pd.DataFrame(
        columns=["temperature_2m", "humidite_relative"],
        index=pd.DatetimeIndex([], tz="UTC"),
    )
    quot = agreger_critere_journalier(df)
    assert quot.empty
