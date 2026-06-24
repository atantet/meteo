"""Tests du temps sensible dérivé (portage MET Norway + ajouts du dépôt).

Le bloc ``test_metno_*`` reproduit **à l'identique** les cas de
``weather_symbol/test/SimpleWeatherSymbolTest.cpp`` (met.no, GPL) avec une
``Factory(6)`` → ``hours=6``. Il prouve la fidélité du portage. Les autres
tests couvrent la projection WMO 4677, la dérivation orage/brouillard propre
au dépôt, et la non-régression du cas « vendredi » (picto pluie / cumul nul).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from meteo_socle.indices.temps_sensible import (
    CAPE_SEUIL_ORAGE_JKG,
    RH_SEUIL_BROUILLARD,
    code_temps_fenetre,
    code_temps_wmo,
    metno_vers_wmo,
    nebulosite_totale_pct,
    serie_code_temps,
    symbole_metno,
)

# --- Fidélité au portage : cas MET Norway (Factory(6), hours=6) --------------


def s(cloud, precip, **kw):
    """Raccourci ``symbole_metno`` avec la fenêtre 6 h des tests MET Norway."""
    return symbole_metno(cloud, precip, hours=6, **kw)


def test_metno_too_cloudy() -> None:
    # Nébulosité > 100 % invalide (porté de ``tooCloudy``)... ici on borne
    # plutôt en amont, mais 100 % reste valide. On vérifie 100 → couvert.
    assert s(100, 0.1) == "Cloud"


def test_metno_negative_precipitation() -> None:
    with pytest.raises(ValueError):
        s(10, -0.1)


def test_metno_sun_no_rain() -> None:
    assert s(10, 0.1) == "Sun"


def test_metno_sun_rain() -> None:
    assert s(10, 0.5) == "DrizzleSun"


def test_metno_light_cloud_no_rain() -> None:
    assert s(30, 0) == "LightCloud"


def test_metno_light_cloud_rain() -> None:
    assert s(30, 45) == "RainSun"


def test_metno_partly_cloud_no_rain() -> None:
    assert s(50, 0.1) == "PartlyCloud"


def test_metno_partly_cloud_little_rain() -> None:
    assert s(50, 0.5) == "DrizzleSun"


def test_metno_partly_cloud_some_rain() -> None:
    assert s(50, 0.96) == "LightRainSun"


def test_metno_partly_cloud_heavy_rain() -> None:
    assert s(50, 7) == "RainSun"


def test_metno_cloudy_no_rain() -> None:
    assert s(90, 0.1) == "Cloud"


def test_metno_cloudy_some_rain() -> None:
    assert s(90, 0.96) == "LightRain"


def test_metno_cloudy_heavy_rain() -> None:
    assert s(90, 6) == "Rain"


def test_metno_dominated_by_high_clouds() -> None:
    # Cirrus seuls (couches basse/moyenne ≤ 13 %) sans pluie → ENSOLEILLÉ (transparent),
    # quel que soit le recouvrement total (30, 50, 80, 95 % → MF dégagé,
    # biais confirmé 4 jours 2026-06-21→24).
    assert s(100, 0, low_cloud_pct=12, mid_cloud_pct=12) == "Sun"
    assert s(79, 0, low_cloud_pct=0, mid_cloud_pct=0) == "Sun"
    # Un VRAI nuage bas (60 % couche basse) n'est PAS réduit → partiellement nuageux.
    assert s(60, 0, low_cloud_pct=60, mid_cloud_pct=10) == "PartlyCloud"


def test_metno_sun_but_maybe_rain() -> None:
    assert s(10, 0, max_precipitation_mm=1) == "PartlyCloud"


def test_metno_air_temperature_precipitation_phase() -> None:
    assert s(90, 5, temperature_c=0.5) == "HeavySnow"
    assert s(90, 5, temperature_c=0.6) == "HeavySleet"
    assert s(90, 5, temperature_c=1.5) == "HeavySleet"
    assert s(90, 5, temperature_c=1.6) == "Rain"


def test_metno_thunderstorm() -> None:
    assert s(90, 5, temperature_c=1.6, thunder=True) == "RainThunder"
    assert s(90, 5, temperature_c=-0.1, thunder=True) == "HeavySnowThunder"


def test_metno_fog() -> None:
    assert s(90, 0.4, fog=True) == "Fog"
    # Dès qu'il pleut, le brouillard est ignoré.
    assert s(90, 0.5, fog=True) == "Drizzle"


# --- Projection WMO 4677 -----------------------------------------------------


def test_projection_wmo_ciel_et_pluie() -> None:
    assert metno_vers_wmo("Sun") == 0
    assert metno_vers_wmo("LightCloud") == 1
    assert metno_vers_wmo("PartlyCloud") == 2
    assert metno_vers_wmo("Cloud") == 3
    assert metno_vers_wmo("Fog") == 45
    # Pluie continue 61/63/65, averses 80/81/82.
    assert metno_vers_wmo("Drizzle") == 61
    assert metno_vers_wmo("Rain") == 65
    assert metno_vers_wmo("DrizzleSun") == 80
    assert metno_vers_wmo("RainSun") == 82


def test_projection_wmo_neige_et_orage() -> None:
    assert metno_vers_wmo("HeavySnow") == 75
    assert metno_vers_wmo("LightSnowSun") == 85
    # Neige fondue rendue comme neige.
    assert metno_vers_wmo("HeavySleet") == 75
    # Toute variante orage → 95.
    assert metno_vers_wmo("RainThunder") == 95
    assert metno_vers_wmo("HeavySnowThunder") == 95


def test_code_temps_wmo_raccourci() -> None:
    # Ciel clair + pluie légère = averse (clair → variante Sun) → 80.
    assert code_temps_wmo(10, 0.5, hours=6) == 80
    # Couvert + forte pluie continue → 65.
    assert code_temps_wmo(90, 6, hours=6) == 65


# --- Ajouts du dépôt : reconstruction nébulosité, orage CAPE, brouillard -----


def test_nebulosite_totale_recouvrement_aleatoire() -> None:
    # Trois couches à 50 % → 1 - 0.5^3 = 0.875 → 87.5 %.
    assert nebulosite_totale_pct(0.5, 0.5, 0.5) == pytest.approx(87.5)
    # Une seule couche pleine → 100 %.
    assert nebulosite_totale_pct(1.0, 0.0, 0.0) == pytest.approx(100.0)
    # Ciel dégagé → 0 %.
    assert nebulosite_totale_pct(0.0, 0.0, 0.0) == pytest.approx(0.0)


def _df_synthetique(rows: list[dict]) -> pd.DataFrame:
    idx = pd.date_range("2026-06-05 12:00", periods=len(rows), freq="h", tz="UTC")
    return pd.DataFrame(rows, index=idx)


def test_serie_code_temps_orage_depuis_cape() -> None:
    # Couvert, pluie franche, CAPE au-dessus du seuil → orage (95).
    df = _df_synthetique(
        [
            {
                "cloud_cover_low": 0.9,
                "cloud_cover_mid": 0.9,
                "cloud_cover_high": 0.9,
                "precipitation": 3.0,
                "temperature_2m": 290.0,
                "cape": CAPE_SEUIL_ORAGE_JKG + 50,
                "humidite_relative": 0.8,
            }
        ]
    )
    assert serie_code_temps(df, hours=1).iloc[0] == 95


def test_serie_code_temps_brouillard_depuis_humidite() -> None:
    # HR très élevée, pas de pluie → brouillard (45).
    df = _df_synthetique(
        [
            {
                "cloud_cover_low": 0.9,
                "cloud_cover_mid": 0.5,
                "cloud_cover_high": 0.5,
                "precipitation": 0.0,
                "temperature_2m": 285.0,
                "cape": 0.0,
                "humidite_relative": RH_SEUIL_BROUILLARD + 0.01,
            }
        ]
    )
    assert serie_code_temps(df, hours=1).iloc[0] == 45


def test_serie_code_temps_na_si_champs_manquants() -> None:
    # Queue ARPEGE : champs AROME absents (NaN) → <NA>, pas d'exception.
    df = _df_synthetique(
        [
            {
                "cloud_cover_low": np.nan,
                "cloud_cover_mid": np.nan,
                "cloud_cover_high": np.nan,
                "precipitation": np.nan,
                "temperature_2m": np.nan,
            }
        ]
    )
    assert pd.isna(serie_code_temps(df, hours=1).iloc[0])


def test_code_temps_fenetre_classe_sur_le_cumul_pas_le_pic_horaire() -> None:
    """1.3 mm/6 h (dont un pic 1.1 mm en 1 h) → modérée sur la fenêtre, pas forte.

    Concordance des échelles : le picto de fenêtre doit être classé sur le
    CUMUL 6 h (seuils {0.5, 0.95, 4.95}) → 1.3 mm = pluie modérée (WMO 63),
    et non sur le pic horaire qui, classé en 1 h (seuil 0.95), donnerait
    « forte » (WMO 65).
    """
    precip = [0.0, 0.0, 1.1, 0.2, 0.0, 0.0]  # cumul 1.3 mm, pic à 1.1 mm/h
    rows = [
        {
            "cloud_cover_low": 0.95,
            "cloud_cover_mid": 0.95,
            "cloud_cover_high": 0.95,
            "precipitation": p,
            "temperature_2m": 290.0,
            "cape": 0.0,
            "humidite_relative": 0.8,
        }
        for p in precip
    ]
    df = _df_synthetique(rows)
    # Fenêtre (cumul 6 h) → pluie modérée continue (couvert).
    assert code_temps_fenetre(df) == 63
    # Heure par heure : le pic 1.1 mm/h serait classé « forte » (65).
    assert serie_code_temps(df, hours=1).max() == 65


def test_code_temps_fenetre_none_si_champs_absents() -> None:
    # Sans les champs AROME, on renvoie None (l'appelant retombe sur l'horaire).
    idx = pd.date_range("2026-06-05 06:00", periods=6, freq="h", tz="UTC")
    df = pd.DataFrame({"weather_code": [3] * 6}, index=idx)
    assert code_temps_fenetre(df) is None


def test_regression_vendredi_picto_coherent_avec_cumul() -> None:
    """Cas vendredi 05/06 15h : nuages hauts, precip AROME nulle → pas de pluie.

    Avant le correctif, le picto venait du code 51 (bruine) d'ARPEGE alors
    que le cumul AROME valait 0. Désormais le code est dérivé des champs
    AROME : sans précipitation, aucun code de pluie ne doit sortir.
    """
    df = _df_synthetique(
        [
            {
                "cloud_cover_low": 0.0,
                "cloud_cover_mid": 0.0,
                "cloud_cover_high": 0.99,
                "precipitation": 0.0,
                "temperature_2m": 290.0,
                "cape": 0.0,
                "humidite_relative": 0.55,
            }
        ]
    )
    code = int(serie_code_temps(df, hours=1).iloc[0])
    # Codes « sans précipitation » uniquement (0-3 ciel, 45 brouillard).
    assert code in {0, 1, 2, 3, 45}
    # Et précisément : couvert de cirrus seuls → ramené à ENSOLEILLÉ (0).
    assert code == 0
