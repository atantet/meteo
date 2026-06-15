"""Tests offline de la source ECMWF Open Data (zéro réseau).

Couvrent la logique de conversion vers le socle (Magnus, dé-accumulation,
échéances), l'assemblage depuis des datasets cfgrib synthétiques, et le cache.
Le fetch réseau (`_telecharger`) est injecté/mocké.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from meteo_socle.sources.ecmwf_opendata import (  # noqa: E402
    EcmwfOpendata,
    _assembler,
    _deaccumuler,
    _humidite_relative,
    _steps_horizon,
)


def test_humidite_relative_saturation_et_partiel() -> None:
    """Td = T → HR = 1 ; Td < T → HR < 1 ; bornée [0, 1]."""
    t = pd.Series([293.15, 293.15])  # 20 °C
    td = pd.Series([293.15, 283.15])  # 20 °C (saturé) puis 10 °C
    rh = _humidite_relative(t, td)
    assert rh.iloc[0] == pytest.approx(1.0, abs=1e-6)
    assert 0.4 < rh.iloc[1] < 0.6  # ~52 % à 20/10 °C
    assert (rh >= 0).all() and (rh <= 1).all()


def test_steps_horizon_3h_puis_6h() -> None:
    """≤ 144 h en 3-horaire, puis 6-horaire jusqu'à l'horizon (≤ 240 h)."""
    assert _steps_horizon(1) == [0, 3, 6, 9, 12, 15, 18, 21, 24]
    s10 = _steps_horizon(10)
    assert s10[0] == 0 and 144 in s10 and 240 in s10
    assert 150 in s10 and 147 not in s10  # passage au pas 6 h après 144
    assert max(s10) == 240


def test_deaccumuler_precip_mm() -> None:
    """Cumul (m) → incrément par fenêtre × 1000 (mm) ; 1ʳᵉ échéance = 0."""
    idx = pd.date_range("2026-06-12", periods=3, freq="3h", tz="UTC")
    cumul = pd.Series([0.0, 0.001, 0.003], index=idx)  # m cumulés
    out = _deaccumuler(cumul, "mm")
    assert list(out.round(3)) == [0.0, 1.0, 2.0]  # mm par fenêtre


def test_deaccumuler_rayonnement_j_par_h() -> None:
    """Cumul (J/m²) → incrément / durée fenêtre = J/m²/h."""
    idx = pd.date_range("2026-06-12", periods=3, freq="3h", tz="UTC")
    cumul = pd.Series([0.0, 3600.0 * 3, 3600.0 * 3 + 7200.0 * 3], index=idx)
    out = _deaccumuler(cumul, "J_par_h")
    # fenêtre 1 : 10800 J sur 3 h = 3600 J/m²/h ; fenêtre 2 : 21600 J sur 3 h = 7200.
    assert list(out.round(1)) == [0.0, 3600.0, 7200.0]


def test_deaccumuler_increment_negatif_clip_a_zero() -> None:
    """Un incrément négatif (réinit/bruit) est ramené à 0 (jamais de pluie négative)."""
    idx = pd.date_range("2026-06-12", periods=3, freq="3h", tz="UTC")
    cumul = pd.Series([0.0, 0.002, 0.001], index=idx)
    out = _deaccumuler(cumul, "mm")
    assert (out >= 0).all()


def _dataset_synthetique(run: pd.Timestamp, steps: list[int]) -> xr.Dataset:
    """Dataset cfgrib-like : 8 variables, grille 3×3 autour du point, dim ``step``."""
    lats = np.array([49.0, 48.5, 48.0])
    lons = np.array([-2.0, -1.5, -1.0])
    n = len(steps)
    valid = [run.tz_localize(None) + pd.Timedelta(hours=h) for h in steps]

    def champ(base: float, pente: float = 0.0) -> xr.DataArray:
        data = np.zeros((n, 3, 3))
        for i in range(n):
            data[i] = base + pente * i
        return xr.DataArray(
            data,
            dims=["step", "latitude", "longitude"],
            coords={
                "step": [pd.Timedelta(hours=h) for h in steps],
                "latitude": lats,
                "longitude": lons,
                "valid_time": ("step", valid),
            },
        )

    # tp, ssrd cumulés (croissants) ; le reste instantané.
    tp = champ(0.0)
    ssrd = champ(0.0)
    for i in range(n):
        tp.values[i] = 0.001 * i  # m cumulés
        ssrd.values[i] = 1.0e6 * i  # J/m² cumulés
    return xr.Dataset(
        {
            "t2m": champ(290.0, 0.5),
            "d2m": champ(285.0),
            "u10": champ(3.0),  # vent d'ouest (U>0) → direction ~270
            "v10": champ(0.0),
            "fg10": champ(7.0),
            "tcc": champ(0.5),
            "tp": tp,
            "ssrd": ssrd,
        }
    )


def test_assembler_produit_un_df_socle_horaire() -> None:
    """Datasets synthétiques → df unités socle, horaire, vent dérivé, sans colonnes brutes."""
    run = pd.Timestamp("2026-06-12 00:00", tz="UTC")
    steps = list(range(0, 25, 3))
    ds = _dataset_synthetique(run, steps)
    df = _assembler([ds], run, horizon_jours=1, latitude=48.544, longitude=-1.612)

    # Colonnes socle attendues, pas de colonnes brutes U/V.
    for col in (
        "temperature_2m",
        "humidite_relative",
        "rafales_vent_10m",
        "cloud_cover",
        "precipitation",
        "rayonnement_global",
        "vitesse_vent_10m",
        "direction_vent_deg",
    ):
        assert col in df.columns
    assert "_u10" not in df.columns and "_v10" not in df.columns
    # Index horaire uniforme.
    assert (df.index.to_series().diff().dropna() == pd.Timedelta(hours=1)).all()
    # Unités plausibles : T en K, HR/nébulosité fraction, vent d'ouest → ~270°.
    assert (df.temperature_2m > 250).all() and (df.temperature_2m < 320).all()
    assert (df.humidite_relative.between(0, 1)).all()
    assert df.direction_vent_deg.dropna().between(255, 285).all()
    assert (df.precipitation >= 0).all()


def test_assembler_ptype_sf_presents() -> None:
    """ptype (code, passthrough) et sf (neige cumulée m → mm) traités quand présents."""
    run = pd.Timestamp("2026-06-12 00:00", tz="UTC")
    steps = list(range(0, 13, 3))
    ds = _dataset_synthetique(run, steps)
    ptype = xr.zeros_like(ds["t2m"]) + 1.0  # code 1 = pluie (passé tel quel)
    sf = xr.zeros_like(ds["t2m"])
    for i in range(len(steps)):
        sf.values[i] = 0.0005 * i  # m cumulés
    ds = ds.assign(ptype=ptype, sf=sf)
    df = _assembler([ds], run, horizon_jours=1, latitude=48.544, longitude=-1.612)
    assert "type_precip" in df.columns and "precipitation_neige" in df.columns
    assert (df.type_precip == 1.0).all()  # code, pas de conversion
    assert (df.precipitation_neige >= 0).all()
    assert df.precipitation_neige.sum() > 0  # m → mm, réparti à l'heure


def test_assembler_ptype_sf_absents_nan() -> None:
    """Sans ptype/sf dans le run : colonnes présentes mais le type de précip est NaN."""
    run = pd.Timestamp("2026-06-12 00:00", tz="UTC")
    ds = _dataset_synthetique(run, list(range(0, 13, 3)))
    df = _assembler([ds], run, horizon_jours=1, latitude=48.544, longitude=-1.612)
    assert "type_precip" in df.columns
    assert df.type_precip.isna().all()  # instantané absent → NaN (pas de phase)


def test_obtenir_run_cache_hit_sans_reseau(tmp_path: Path) -> None:
    """Si le parquet de cache existe, aucun téléchargement n'est tenté."""
    run = pd.Timestamp("2026-06-12 00:00", tz="UTC")
    cache = tmp_path / f"ecmwf_{run:%Y%m%dT%HZ}_48.544_-1.612_h4.parquet"
    attendu = pd.DataFrame(
        {"temperature_2m": [290.0]},
        index=pd.DatetimeIndex([run], name="time"),
    )
    attendu.to_parquet(cache)

    class _ClientInterdit:
        def retrieve(self, **kwargs):
            raise AssertionError("aucun fetch attendu en cache hit")

    src = EcmwfOpendata(client=_ClientInterdit())
    df = src.obtenir_run(run, 48.544, -1.612, 4, cache_dir=tmp_path)
    assert df["temperature_2m"].iloc[0] == 290.0
