"""Tests unitaires des helpers purs d'ARPEGE direct MF (sans réseau).

Le fetch WCS lui-même (OAuth + GetCoverage + GRIB) nécessite réseau + token MF :
non testé en CI. On verrouille ici les parties déterministes — surtout les
conventions d'unités et la direction du vent, sources classiques de bugs.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from meteo_socle.sources.meteofrance_arpege import (
    MeteoFranceArpege,
    _convertir,
    _coverage_run,
    _LimiteurDebit,
    _reechantillonner_horaire,
    _suffixe_accum,
    vent_vitesse_direction,
)


@pytest.mark.parametrize(
    ("u", "v", "dir_attendue"),
    [
        (0.0, -1.0, 0.0),  # souffle vers le sud → vient du nord
        (-1.0, 0.0, 90.0),  # vers l'ouest → vient de l'est
        (0.0, 1.0, 180.0),  # vers le nord → vient du sud
        (1.0, 0.0, 270.0),  # vers l'est → vient de l'ouest
    ],
)
def test_vent_direction_cardinaux(u: float, v: float, dir_attendue: float) -> None:
    vitesse, direction = vent_vitesse_direction(u, v)
    assert vitesse == pytest.approx(1.0)
    assert direction == pytest.approx(dir_attendue)


def test_vent_vectorise() -> None:
    u = pd.Series([3.0, 0.0])
    v = pd.Series([4.0, -2.0])
    vit, _ = vent_vitesse_direction(u, v)
    assert list(vit.round(2)) == [5.0, 2.0]


def test_convertir_unites() -> None:
    assert _convertir(88.0, "pct_frac") == pytest.approx(0.88)  # % → fraction
    # J/m² accumulés sur la fenêtre → J/m²/h (socle) : même flux quel que soit le pas.
    assert _convertir(3600.0, "J_par_h", fenetre_s=3600.0) == pytest.approx(3600.0)  # 1 h
    assert _convertir(10800.0, "J_par_h", fenetre_s=10800.0) == pytest.approx(3600.0)  # 3 h → E/3
    assert _convertir(288.15, "K") == pytest.approx(288.15)  # passthrough


def test_suffixe_accumulation() -> None:
    assert _suffixe_accum(3600.0) == "_PT1H"
    assert _suffixe_accum(10800.0) == "_PT3H"


def test_coverage_run_format() -> None:
    run = pd.Timestamp("2026-06-12 00:00", tz="UTC")
    assert _coverage_run(run) == "2026-06-12T00.00.00Z"


def test_limiteur_debit_laisse_passer_la_capacite() -> None:
    lim = _LimiteurDebit(max_par_minute=3)
    for _ in range(3):
        lim.acquerir()  # ne doit pas bloquer sous la capacité
    assert len(lim._instants) == 3


def test_reechantillonnage_horaire_repartit_les_accumulees() -> None:
    """Pas mixte (horaire puis 3-horaire) → horaire ; cumul pluie conservé, flux répété."""
    run = pd.Timestamp("2026-06-12 00:00", tz="UTC")
    h = lambda n: run + pd.Timedelta(hours=n)  # noqa: E731
    df = pd.DataFrame(
        {
            "temperature_2m": [288.0, 288.0, 288.0, 291.0],
            "precipitation": [0.0, 0.5, 0.5, 3.0],  # +5 h = cumul de la fenêtre 3 h
            "rayonnement_global": [0.0, 100.0, 200.0, 300.0],  # déjà J/m²/h (par heure)
        },
        index=pd.DatetimeIndex([h(0), h(1), h(2), h(5)], name="time"),
    )
    out = _reechantillonner_horaire(df, run)
    assert list(out.index) == [h(n) for n in range(6)]  # 0..5 h, horaire
    assert out["precipitation"].sum() == pytest.approx(4.0)  # cumul conservé
    # Fenêtre 3 h (heures 3,4,5) : pluie répartie /3, rayonnement (J/m²/h) répété.
    assert out["precipitation"].loc[[h(3), h(4), h(5)]].tolist() == pytest.approx([1.0, 1.0, 1.0])
    assert out["rayonnement_global"].loc[[h(3), h(4), h(5)]].tolist() == pytest.approx(
        [300.0, 300.0, 300.0]
    )


def test_cache_hit_evite_le_reseau(tmp_path: Path) -> None:
    """Run en cache → obtenir_run le renvoie sans réseau (pas d'OAuth déclenché)."""
    run = pd.Timestamp("2026-06-12 00:00", tz="UTC")
    lat, lon = 48.544, -1.612
    attendu = pd.DataFrame(
        {"temperature_2m": [288.0, 289.0]},
        index=pd.DatetimeIndex([run, run + pd.Timedelta(hours=1)], name="time"),
    )
    chemin = tmp_path / f"arpege_{run:%Y%m%dT%HZ}_{lat:.3f}_{lon:.3f}_h4.parquet"
    attendu.to_parquet(chemin)
    # basic bidon : si le réseau était touché (OAuth), ça lèverait → le cache l'évite.
    src = MeteoFranceArpege(basic="bidon")
    out = src.obtenir_run(run, lat, lon, horizon_jours=4, cache_dir=tmp_path)
    pd.testing.assert_frame_equal(out, attendu)
