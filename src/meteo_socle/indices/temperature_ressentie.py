"""Température ressentie selon l'algorithme officiel Météo-France.

Météo-France applique deux indices selon la condition thermique
(source : meteofrance.com/magazine/meteo-questions/quest-ce-que-la-temperature-ressentie) :

- **Windchill** (refroidissement éolien) quand T ≤ 10 °C et V ≥ 5 km/h.
  Formule NWS 2001 (NOAA / Environment Canada), adoptée par les services
  météo nationaux dont Météo-France :

      T_wc = 13,12 + 0,6215·T − 11,37·V^0,16 + 0,3965·T·V^0,16

  T en °C, V en km/h. La formule donne toujours T_wc ≤ T.

- **Humidex** (indice de confort par chaleur-humidité) quand T ≥ 15 °C.
  Formule Environment Canada, adoptée par Météo-France :

      e = 6,112 · exp(17,67 · T_dp / (T_dp + 243,5))
      H  = T + 5/9 · (e − 10)

  T_dp (point de rosée, °C) dérivé de T et HR par l'approximation de
  Magnus (Alduchov & Eskridge 1996). On n'affiche H que si H > T
  (sinon T inchangée — faible humidité, pas de sur-chaleur).

- **T inchangée** dans tous les autres cas (10 < T < 15 °C, ou vent faible
  sous 10 °C, ou humidité ne créant pas de sur-chaleur).

Entrées (unités socle) :
  - ``temp_c``       : température de l'air (°C).
  - ``vitesse_ms``   : vitesse du vent à 10 m (m/s).
  - ``humidite_frac``: humidité relative (fraction 0-1).

Références
----------
- Météo-France, *Qu'est-ce que la température ressentie ?*
  <https://meteofrance.com/magazine/meteo-questions/quest-ce-que-la-temperature-ressentie>
- NOAA / Environment Canada, *Wind Chill Temperature Index*, 2001.
- Alduchov, O.A. & Eskridge, R.E., 1996. *Improved Magnus Form Approximation
  of Saturation Vapor Pressure.* J. Appl. Meteor., 35, 601-609.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constantes des formules
# ---------------------------------------------------------------------------

#: Borne haute T (°C) du domaine windchill (MF : < 10 °C).
T_MAX_WINDCHILL_C = 10.0
#: Vent minimum (km/h) pour activer le windchill.
V_MIN_WINDCHILL_KMH = 5.0
#: Borne basse T (°C) du domaine humidex (MF : > 15 °C).
T_MIN_HUMIDEX_C = 15.0


def _windchill_c(temp_c: np.ndarray, v_kmh: np.ndarray) -> np.ndarray:
    """Windchill NWS 2001 (scalaires ou tableaux NumPy)."""
    return 13.12 + 0.6215 * temp_c - 11.37 * v_kmh**0.16 + 0.3965 * temp_c * v_kmh**0.16


def _point_rosee_c(temp_c: np.ndarray, humidite_frac: np.ndarray) -> np.ndarray:
    """Point de rosée (°C) par l'approximation de Magnus (Alduchov & Eskridge 1996)."""
    rh = np.clip(humidite_frac, 1e-6, 1.0)
    gamma = np.log(rh) + 17.625 * temp_c / (243.04 + temp_c)
    return 243.04 * gamma / (17.625 - gamma)


def _humidex_c(temp_c: np.ndarray, humidite_frac: np.ndarray) -> np.ndarray:
    """Humidex Environment Canada (scalaires ou tableaux NumPy)."""
    t_dp = _point_rosee_c(temp_c, humidite_frac)
    e = 6.112 * np.exp(17.67 * t_dp / (t_dp + 243.5))
    return temp_c + 5.0 / 9.0 * (e - 10.0)


def temperature_ressentie_serie(
    temp_c: pd.Series,
    vitesse_ms: pd.Series,
    humidite_frac: pd.Series,
) -> pd.Series:
    """Température ressentie (°C) — algorithme MF — sur une série horaire.

    Les trois séries doivent partager le même index (déjà le cas pour les
    colonnes d'un même DataFrame AROME). Les NaN dans ``vitesse_ms`` ou
    ``humidite_frac`` sont traités comme « condition absente » : on retombe
    sur T (ou sur l'autre indice si applicable).

    Retourne une ``Series`` de même index que ``temp_c``.
    """
    t = temp_c.to_numpy(dtype=float)
    v_ms = vitesse_ms.reindex(temp_c.index).to_numpy(dtype=float)
    rh = humidite_frac.reindex(temp_c.index).to_numpy(dtype=float)
    v_kmh = v_ms * 3.6

    result = t.copy()

    # Windchill : T ≤ 10 °C et V ≥ 5 km/h et V non-NaN.
    mask_wc = (t <= T_MAX_WINDCHILL_C) & (v_kmh >= V_MIN_WINDCHILL_KMH) & ~np.isnan(v_kmh)
    if mask_wc.any():
        result[mask_wc] = _windchill_c(t[mask_wc], v_kmh[mask_wc])

    # Humidex : T ≥ 15 °C et HR non-NaN et H > T.
    mask_hx_cand = (t >= T_MIN_HUMIDEX_C) & ~np.isnan(rh)
    if mask_hx_cand.any():
        h = _humidex_c(t[mask_hx_cand], rh[mask_hx_cand])
        mask_hx = mask_hx_cand.copy()
        mask_hx[mask_hx_cand] = h > t[mask_hx_cand]
        result[mask_hx] = _humidex_c(t[mask_hx], rh[mask_hx])

    return pd.Series(result, index=temp_c.index, name="temperature_ressentie_c")
