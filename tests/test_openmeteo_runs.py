"""Tests unitaires `meteo_socle.sources.openmeteo_runs` (Single Runs, mock HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests

from meteo_socle.sources.openmeteo_runs import (
    AROME,
    ARPEGE,
    ECMWF,
    ECMWF_HRES,
    OpenMeteoSingleRuns,
    PrevisionIndisponibleError,
    ancre_creneau,
    creneau_run,
    creneaux_precedents,
    fusionner_priorite,
    runs_du_creneau,
)

# --------------------------------------------------------------------------- #
# Sélection de run déterministe (D3/D4)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("heure_utc", "creneau_attendu", "jour_offset"),
    [
        ("2024-06-15 04:30:00+00:00", "apres-midi", -1),  # nuit → après-midi veille
        ("2024-06-15 05:30:00+00:00", "matin", 0),  # borne matin (inclusive)
        ("2024-06-15 09:00:00+00:00", "matin", 0),
        ("2024-06-15 17:29:00+00:00", "matin", 0),
        ("2024-06-15 17:30:00+00:00", "apres-midi", 0),  # borne après-midi (inclusive)
        ("2024-06-15 22:00:00+00:00", "apres-midi", 0),
        ("2024-06-15 00:30:00+00:00", "apres-midi", -1),
    ],
)
def test_creneau_run_bornes(heure_utc: str, creneau_attendu: str, jour_offset: int) -> None:
    creneau, jour = creneau_run(pd.Timestamp(heure_utc))
    assert creneau == creneau_attendu
    attendu = pd.Timestamp("2024-06-15 00:00:00+00:00") + pd.Timedelta(days=jour_offset)
    assert jour == attendu


def test_runs_du_creneau_matin() -> None:
    jour = pd.Timestamp("2024-06-15 00:00:00+00:00")
    runs = runs_du_creneau("matin", jour)
    assert runs[AROME] == pd.Timestamp("2024-06-15 00:00:00+00:00")
    assert runs[ARPEGE] == pd.Timestamp("2024-06-15 00:00:00+00:00")
    # ECMWF-ENS (proba) un cran (6 h) derrière → 18Z de la veille.
    assert runs[ECMWF] == pd.Timestamp("2024-06-14 18:00:00+00:00")
    # ECMWF-HRES (tendance longue) = dernier run long 00/12Z → 12Z de la veille.
    assert runs[ECMWF_HRES] == pd.Timestamp("2024-06-14 12:00:00+00:00")


def test_runs_du_creneau_apres_midi() -> None:
    jour = pd.Timestamp("2024-06-15 00:00:00+00:00")
    runs = runs_du_creneau("apres-midi", jour)
    assert runs[AROME] == pd.Timestamp("2024-06-15 12:00:00+00:00")
    assert runs[ECMWF] == pd.Timestamp("2024-06-15 06:00:00+00:00")
    # ECMWF-HRES après-midi → 00Z du jour.
    assert runs[ECMWF_HRES] == pd.Timestamp("2024-06-15 00:00:00+00:00")


def test_ancre_creneau_est_init_run_coeur() -> None:
    # Matin → 00Z du jour ; après-midi → 12Z.
    assert ancre_creneau(pd.Timestamp("2024-06-15 09:00:00+00:00")) == pd.Timestamp(
        "2024-06-15 00:00:00+00:00"
    )
    assert ancre_creneau(pd.Timestamp("2024-06-15 18:00:00+00:00")) == pd.Timestamp(
        "2024-06-15 12:00:00+00:00"
    )


# --------------------------------------------------------------------------- #
# Fusion par priorité (D2)
# --------------------------------------------------------------------------- #


def test_fusionner_priorite_arome_gagne_arpege_comble() -> None:
    idx = pd.date_range("2024-06-15 00:00", periods=3, freq="h", tz="UTC")
    # AROME : 0-2 h, cœur sans rayonnement.
    arome = pd.DataFrame(
        {"temperature_2m": [283.15, 283.15, 283.15], "rayonnement_global": [float("nan")] * 3},
        index=idx,
    )
    # ARPEGE : 0-2 h, température différente (ne doit PAS gagner) + rayonnement.
    arpege = pd.DataFrame(
        {"temperature_2m": [284.0, 284.0, 284.0], "rayonnement_global": [0.0, 360000.0, 720000.0]},
        index=idx,
    )
    fusion = fusionner_priorite([arome, arpege])
    # AROME prioritaire sur la température.
    assert fusion["temperature_2m"].iloc[0] == pytest.approx(283.15)
    # Rayonnement comblé par ARPEGE (AROME NaN).
    assert fusion["rayonnement_global"].iloc[1] == pytest.approx(360000.0)


def test_fusionner_priorite_etend_la_queue_au_dela_dhorizon_arome() -> None:
    # AROME ne couvre que 0-1 h ; ARPEGE couvre 0-3 h → la queue vient d'ARPEGE.
    arome = pd.DataFrame(
        {"temperature_2m": [283.15, 283.15]},
        index=pd.date_range("2024-06-15 00:00", periods=2, freq="h", tz="UTC"),
    )
    arpege = pd.DataFrame(
        {"temperature_2m": [284.0, 284.0, 284.0, 284.0]},
        index=pd.date_range("2024-06-15 00:00", periods=4, freq="h", tz="UTC"),
    )
    fusion = fusionner_priorite([arome, arpege])
    assert len(fusion) == 4
    assert fusion["temperature_2m"].iloc[0] == pytest.approx(283.15)  # AROME
    assert fusion["temperature_2m"].iloc[3] == pytest.approx(284.0)  # ARPEGE (queue)


# --------------------------------------------------------------------------- #
# Fetch HTTP (mock)
# --------------------------------------------------------------------------- #


def _resp(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(str(status))
    else:
        r.raise_for_status = MagicMock()
    return r


def _payload(**colonnes: list) -> dict:
    times = ["2024-06-15T00:00", "2024-06-15T01:00", "2024-06-15T02:00"]
    return {"hourly": {"time": times, **colonnes}}


_PAYLOAD_AROME = _payload(
    temperature_2m=[10.0, 10.0, 10.0],
    relative_humidity_2m=[80.0, 80.0, 80.0],
    precipitation=[0.0, 0.0, 0.0],
    wind_speed_10m=[5.0, 5.0, 5.0],
    wind_gusts_10m=[9.0, 9.0, 9.0],
    wind_direction_10m=[270.0, 270.0, 270.0],
    weather_code=[1, 1, 1],
    cloud_cover=[50.0, 50.0, 50.0],
)
_PAYLOAD_ARPEGE = _payload(
    temperature_2m=[11.0, 11.0, 11.0],  # différent → vérifie priorité AROME
    shortwave_radiation=[0.0, 100.0, 200.0],
)
_PAYLOAD_ECMWF = _payload(precipitation_probability=[10.0, 20.0, 30.0])


def _session_par_modele(payloads: dict[str, dict | None]) -> MagicMock:
    """Mock session qui dispatche la réponse selon le paramètre ``models``.

    Une valeur ``None`` simule un run muet (HTTP 400).
    """
    sess = MagicMock()

    def _get(url, params=None, timeout=None):  # noqa: ANN001, ANN202
        p = payloads.get(params["models"])
        return _resp({}, status=400) if p is None else _resp(p)

    sess.get.side_effect = _get
    return sess


def test_obtenir_run_conversions_et_param_run() -> None:
    sess = _session_par_modele({AROME: _PAYLOAD_AROME})
    client = OpenMeteoSingleRuns(session=sess)
    df = client.obtenir_run(
        AROME,
        pd.Timestamp("2024-06-15 00:00:00+00:00"),
        48.54,
        -1.62,
        horizon_jours=3,
        variables=("temperature_2m",),
    )
    assert df is not None
    assert df["temperature_2m"].iloc[0] == pytest.approx(283.15)  # °C → K
    assert df["humidite_relative"].iloc[0] == pytest.approx(0.80)  # % → fraction
    # Le run est transmis au format ISO sans secondes.
    params = sess.get.call_args.kwargs["params"]
    assert params["run"] == "2024-06-15T00:00"
    assert params["models"] == AROME


def test_obtenir_run_muet_renvoie_none() -> None:
    sess = _session_par_modele({AROME: None})  # 400
    client = OpenMeteoSingleRuns(session=sess)
    df = client.obtenir_run(
        AROME, pd.Timestamp("2024-06-15 00:00:00+00:00"), 0, 0, 3, ("temperature_2m",)
    )
    assert df is None


def test_obtenir_run_payload_vide_renvoie_none() -> None:
    sess = _session_par_modele({AROME: {"hourly": {"time": []}}})
    client = OpenMeteoSingleRuns(session=sess)
    df = client.obtenir_run(
        AROME, pd.Timestamp("2024-06-15 00:00:00+00:00"), 0, 0, 3, ("temperature_2m",)
    )
    assert df is None


# --------------------------------------------------------------------------- #
# Orchestration fusion App 1 (D2 + D8)
# --------------------------------------------------------------------------- #


def test_obtenir_prevision_fusion_complete() -> None:
    sess = _session_par_modele(
        {AROME: _PAYLOAD_AROME, ARPEGE: _PAYLOAD_ARPEGE, ECMWF: _PAYLOAD_ECMWF}
    )
    client = OpenMeteoSingleRuns(session=sess)
    res = client.obtenir_prevision(48.54, -1.62, 3, pd.Timestamp("2024-06-15 09:00:00+00:00"))

    # Cœur AROME prioritaire (10 °C, pas 11 d'ARPEGE).
    assert res.df["temperature_2m"].iloc[0] == pytest.approx(283.15)
    # Rayonnement comblé par ARPEGE.
    assert res.df["rayonnement_global"].iloc[1] == pytest.approx(100.0 * 3600.0)
    # Proba comblée par ECMWF.
    assert res.df["probabilite_pluie_pct"].iloc[2] == pytest.approx(30.0)
    # Provenance : 3 runs servis, créneau matin, ancre = 00Z J.
    assert set(res.runs_utilises) == {AROME, ARPEGE, ECMWF}
    assert res.creneau == "matin"
    assert res.ancre_utc == pd.Timestamp("2024-06-15 00:00:00+00:00")
    assert res.runs_utilises[ECMWF] == pd.Timestamp("2024-06-14 18:00:00+00:00")


def test_obtenir_prevision_omet_proba_si_ecmwf_muet() -> None:
    # ECMWF (proba) muet → la contribution est omise, le reste part (D8).
    sess = _session_par_modele({AROME: _PAYLOAD_AROME, ARPEGE: _PAYLOAD_ARPEGE, ECMWF: None})
    client = OpenMeteoSingleRuns(session=sess)
    res = client.obtenir_prevision(48.54, -1.62, 3, pd.Timestamp("2024-06-15 09:00:00+00:00"))

    assert "probabilite_pluie_pct" not in res.df.columns
    assert res.df["temperature_2m"].iloc[0] == pytest.approx(283.15)
    assert ECMWF not in res.runs_utilises
    assert {AROME, ARPEGE} <= set(res.runs_utilises)


def test_obtenir_prevision_tout_muet_leve_indisponible() -> None:
    sess = _session_par_modele({AROME: None, ARPEGE: None, ECMWF: None})
    client = OpenMeteoSingleRuns(session=sess)
    with pytest.raises(PrevisionIndisponibleError):
        client.obtenir_prevision(48.54, -1.62, 3, pd.Timestamp("2024-06-15 09:00:00+00:00"))


# --------------------------------------------------------------------------- #
# Stitch déterministe du passé — App 2 (D6)
# --------------------------------------------------------------------------- #


def test_creneaux_precedents_depuis_matin() -> None:
    # Depuis (matin, 15/06) → 4 créneaux précédents, pas de 12 h, du + récent
    # au + ancien.
    prec = creneaux_precedents(pd.Timestamp("2024-06-15 06:00:00+00:00"), 4)
    j15 = pd.Timestamp("2024-06-15 00:00:00+00:00")
    assert prec == [
        ("apres-midi", j15 - pd.Timedelta(days=1)),
        ("matin", j15 - pd.Timedelta(days=1)),
        ("apres-midi", j15 - pd.Timedelta(days=2)),
        ("matin", j15 - pd.Timedelta(days=2)),
    ]


def _session_par_run(payloads_par_run: dict[str, dict | None]) -> MagicMock:
    """Mock session qui dispatche selon le paramètre ``run`` (run muet si None)."""
    sess = MagicMock()

    def _get(url, params=None, timeout=None):  # noqa: ANN001, ANN202
        p = payloads_par_run.get(params["run"])
        return _resp({}, status=400) if p is None else _resp(p)

    sess.get.side_effect = _get
    return sess


def _payload_run(run_utc: pd.Timestamp, marqueur: float, n_heures: int) -> dict:
    """Payload où la T° (°C) = ``marqueur`` constant (encode le run source)."""
    times = pd.date_range(run_utc, periods=n_heures, freq="h", tz="UTC")
    iso = [t.strftime("%Y-%m-%dT%H:%M") for t in times]
    return {"hourly": {"time": iso, "temperature_2m": [marqueur] * n_heures}}


def test_obtenir_serie_avec_passe_stitch_arpege_matin() -> None:
    """Stitch ARPEGE créneau matin : 4 segments passés (12 h) + run courant.

    Chaque run porte un marqueur de T° distinct → on vérifie que chaque heure
    vient du bon run, et que le pavage est continu de J-2 à l'horizon.
    """
    # Runs attendus (créneau matin J=15/06) : courant 00Z 15 ; passé 12Z 14,
    # 00Z 14, 12Z 13, 00Z 13.
    r_cur = pd.Timestamp("2024-06-15 00:00:00+00:00")
    r_p1 = pd.Timestamp("2024-06-14 12:00:00+00:00")
    r_p2 = pd.Timestamp("2024-06-14 00:00:00+00:00")
    r_p3 = pd.Timestamp("2024-06-13 12:00:00+00:00")
    r_p4 = pd.Timestamp("2024-06-13 00:00:00+00:00")

    def _iso(ts: pd.Timestamp) -> str:
        return ts.strftime("%Y-%m-%dT%H:%M")

    payloads = {
        _iso(r_cur): _payload_run(r_cur, 0.0, 96),
        _iso(r_p1): _payload_run(r_p1, 1.0, 24),
        _iso(r_p2): _payload_run(r_p2, 2.0, 24),
        _iso(r_p3): _payload_run(r_p3, 3.0, 24),
        _iso(r_p4): _payload_run(r_p4, 4.0, 24),
    }
    client = OpenMeteoSingleRuns(session=_session_par_run(payloads))
    res = client.obtenir_serie_avec_passe(
        ARPEGE,
        ARPEGE,
        48.54,
        -1.62,
        horizon_jours=4,
        now_utc=pd.Timestamp("2024-06-15 06:00:00+00:00"),
        variables=("temperature_2m",),
        n_jours_passe=2,
    )

    # Provenance.
    assert res.run_courant == r_cur
    assert res.pivot_utc == r_cur
    assert res.runs_passe == [r_p1, r_p2, r_p3, r_p4]

    # Pavage continu [00Z 13 ; 00Z 19) = 48 h passé + 96 h courant = 144 h.
    assert res.df.index[0] == r_p4
    assert len(res.df) == 144

    def _temp_c(ts: str) -> float:
        return float(res.df.loc[pd.Timestamp(ts, tz="UTC"), "temperature_2m"]) - 273.15

    # Chaque heure vient du run le plus récent de son bloc de 12 h.
    assert _temp_c("2024-06-13 06:00") == pytest.approx(4.0)  # run 00Z 13
    assert _temp_c("2024-06-13 18:00") == pytest.approx(3.0)  # run 12Z 13
    assert _temp_c("2024-06-14 06:00") == pytest.approx(2.0)  # run 00Z 14
    assert _temp_c("2024-06-14 18:00") == pytest.approx(1.0)  # run 12Z 14
    assert _temp_c("2024-06-15 06:00") == pytest.approx(0.0)  # run courant 00Z 15


def test_obtenir_serie_avec_passe_segment_passe_muet_saute() -> None:
    """Un run passé muet est sauté (trou) ; la série est tout de même renvoyée."""
    r_cur = pd.Timestamp("2024-06-15 00:00:00+00:00")
    r_p1 = pd.Timestamp("2024-06-14 12:00:00+00:00")

    def _iso(ts: pd.Timestamp) -> str:
        return ts.strftime("%Y-%m-%dT%H:%M")

    # Seuls le run courant et le 1er passé répondent ; les 3 autres sont muets.
    payloads: dict[str, dict | None] = {
        _iso(r_cur): _payload_run(r_cur, 0.0, 96),
        _iso(r_p1): _payload_run(r_p1, 1.0, 24),
    }
    client = OpenMeteoSingleRuns(session=_session_par_run(payloads))
    res = client.obtenir_serie_avec_passe(
        ARPEGE,
        ARPEGE,
        48.54,
        -1.62,
        horizon_jours=4,
        now_utc=pd.Timestamp("2024-06-15 06:00:00+00:00"),
        variables=("temperature_2m",),
        n_jours_passe=2,
    )
    # Seul le segment 12Z 14 est paté + le run courant.
    assert res.runs_passe == [r_p1]
    assert res.df.index[0] == r_p1  # [12Z 14 ; 00Z 15) + courant


def test_obtenir_serie_avec_passe_run_courant_muet_leve() -> None:
    client = OpenMeteoSingleRuns(session=_session_par_run({}))  # tout muet
    with pytest.raises(PrevisionIndisponibleError):
        client.obtenir_serie_avec_passe(
            ARPEGE,
            ARPEGE,
            48.54,
            -1.62,
            horizon_jours=4,
            now_utc=pd.Timestamp("2024-06-15 06:00:00+00:00"),
            variables=("temperature_2m",),
        )
