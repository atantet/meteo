"""Évapotranspiration potentielle de référence (ET₀) par la méthode FAO
Penman-Monteith horaire.

Implémentation des équations 53 à 56 du bulletin FAO Irrigation and
Drainage Paper No. 56 (Allen et al. 1998), avec :

- rayonnement extra-terrestre R_a et position solaire calculés via
  `pvlib` (Holmgren et al. 2018) — plus précis que les formules
  analytiques FAO ;
- estimation du clearness ratio R_s / R_so utilisée pour calculer le
  rayonnement net aux ondes longues R_nl par la formule
  Stefan-Boltzmann corrigée (Eq. 39 FAO 56) ;
- propagation nuit du clearness ratio par forward-fill puis backward-fill
  des dernières valeurs jour ;
- flux de chaleur dans le sol G discriminé jour/nuit (0.1·R_n vs 0.5·R_n)
  conformément à la recommandation FAO horaire (Eq. 45-46).

La paramétrisation suit l'approche **Vannier & Braud (2012)** pour
l'usage de la formule FAO avec un couvert de référence gazon court
(h=0.12 m, r_a = 208/V₂, α=0.23, ε=1.0) — appropriée aux stations
synoptiques MF qui fournissent R_s (et non R_A IR descendant comme
SAFRAN).

Références
----------

- Allen, R.G., Pereira, L.S., Raes, D., Smith, M., 1998.
  *Crop Evapotranspiration — Guidelines for Computing Crop Water
  Requirements*. FAO Irrigation and Drainage Paper No. 56, Rome.
  <https://www.fao.org/4/X0490E/x0490e00.htm>
- Vannier, O., Braud, I., 2012. *Calcul d'une évapotranspiration de
  référence spatialisée pour la modélisation hydrologique à partir des
  données de la réanalyse SAFRAN de Météo-France*. Rapport Cemagref / HAL
  ID hal-02593413. <https://hal.inrae.fr/hal-02593413>
- Holmgren, W.F., Hansen, C.W., Mikofski, M.A., 2018. *pvlib python: a
  python package for modeling solar energy systems*. JOSS 3, 884.
  <https://doi.org/10.21105/joss.00884>
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytz
from pvlib import irradiance, location

# Variables météorologiques utilisées pour le calcul de l'ETP et leur
# méthode d'agrégation journalière (info utilitaire pour les modules
# d'agrégation aval, pas utilisée directement ici).
VARIABLES_CALCUL_ETP: dict[str, str] = {
    "vitesse_vent_10m": "mean",
    "temperature_2m": "mean",
    "humidite_relative": "mean",
    "rayonnement_global": "sum",
}

# Chaleur latente de vaporisation de l'eau (MJ kg⁻¹) — FAO 56 Eq. 8.
LAMBDA: float = 2.45

# Facteur de la constante psychrométrique γ = FACTEUR_GAMMA · P (kPa K⁻¹) —
# FAO 56 Eq. 8.
FACTEUR_GAMMA: float = 0.665e-3

# Constante de Stefan-Boltzmann ramenée en MJ m⁻² K⁻⁴ h⁻¹ — FAO 56 Eq. 39.
SIGMA: float = 2.043e-10

# Albedo du couvert de référence (gazon court bien irrigué) — FAO 56 §3.3.
ALPHA: float = 0.23

# Émissivité du couvert de référence — Vannier & Braud (2012) §3.2.1.
EPSILON: float = 1.0


def calcul_rayonnement_net_ondes_courtes(df: pd.DataFrame) -> pd.Series:
    """Rayonnement net aux ondes courtes R_ns = (1 − α) · R_s.

    Eq. 38 FAO 56.

    Parameters
    ----------
    df :
        DataFrame indexé par le temps contenant la colonne
        ``rayonnement_global`` en J m⁻² h⁻¹.

    Returns
    -------
    pd.Series
        R_ns en MJ m⁻² h⁻¹.
    """
    # Rayonnement solaire incident en MJ m⁻² h⁻¹ (conversion J → MJ).
    r_s = df["rayonnement_global"] * 1.0e-6

    # Calcul du rayonnement net aux ondes courtes.
    return (1 - ALPHA) * r_s


def calcul_rayonnement_net_ondes_longues(
    df: pd.DataFrame, ee: pd.Series, site: location.Location
) -> tuple[pd.Series, pd.Series]:
    """Rayonnement net aux ondes longues R_nl avec correction clearness.

    Eq. 39 FAO 56 : R_nl = σ · T⁴ · (0.34 − 0.14 √eₑ) · (1.35 R_s/R_so − 0.35).

    Le clearness ratio R_s/R_so est calculé à partir du rayonnement
    incident observé et du rayonnement ciel clair pvlib. Pour les heures
    de nuit, on propage la dernière valeur de jour disponible par
    forward-fill (ou backward-fill si la nuit précède le premier jour de
    la série), conformément à la recommandation FAO 56 (Box 11).

    Parameters
    ----------
    df :
        Mêmes colonnes que ``calcul_rayonnement_net_ondes_courtes`` plus
        ``temperature_2m`` en K.
    ee :
        Pression de vapeur effective en kPa (Eq. 14 FAO 56).
    site :
        Objet `pvlib.location.Location` (latitude, longitude, altitude, tz).

    Returns
    -------
    r_nl :
        R_nl en MJ m⁻² h⁻¹.
    zenith :
        Angle zénithal solaire en degrés (réutilisé par `calcul_etp`
        pour discriminer le flux de chaleur sol jour/nuit).
    """
    # Rayonnement solaire incident en MJ m⁻² h⁻¹.
    r_s = df["rayonnement_global"] * 1.0e-6

    # Localisation du temps dans la zone du site.
    time = pd.DatetimeIndex(df.index)
    local_time = time.tz_convert(site.tz)

    # Rayonnement extra-terrestre normal (au plan perpendiculaire à la
    # direction solaire) en MJ m⁻² h⁻¹.
    r_a_dni = irradiance.get_extra_radiation(local_time) * 3600 * 1.0e-6

    # Zénith solaire (degrés).
    zenith = site.get_solarposition(times=local_time)["zenith"]

    # Rayonnement extra-terrestre horizontal R_a.
    r_a = np.maximum(0.0, r_a_dni * np.cos(np.deg2rad(zenith)))

    # Rayonnement ciel clair R_so (Eq. 37 FAO 56).
    r_so = (0.75 + 2.0e-5 * site.altitude) * r_a

    # Conversion du temps vers UTC pour aligner avec df.
    r_so.index = r_so.index.tz_convert("UTC")

    # Clearness ratio R_s / R_so, plafonné à 1.
    clarete = np.minimum(1.0, r_s / r_so)

    # Propagation de la clarté la nuit : on garde la dernière valeur
    # diurne (ffill) puis backfill si la nuit précède le premier jour.
    is_day = zenith.values < 90.0
    is_day_short = np.roll(is_day, 1) & np.roll(is_day, -1)
    clarete = clarete.where(is_day_short).ffill(axis="index").bfill(axis="index")

    # Rayonnement net aux ondes longues (Eq. 39 FAO 56).
    r_nl = SIGMA * df["temperature_2m"] ** 4 * (0.34 - 0.14 * np.sqrt(ee)) * (1.35 * clarete - 0.35)

    return r_nl, zenith


def calcul_etp(
    df: pd.DataFrame,
    latitude: float,
    longitude: float,
    altitude: float,
) -> pd.Series:
    """Évapotranspiration potentielle de référence ET₀ horaire (mm h⁻¹).

    Implémente l'équation FAO 56 Penman-Monteith horaire (Eq. 53), avec
    décomposition jour/nuit du flux de chaleur sol G (Eq. 45-46),
    conversion vent 10 m → 2 m (Eq. 47), pression atmosphérique standard
    en fonction de l'altitude (Eq. 7).

    Parameters
    ----------
    df :
        DataFrame indexé par un DatetimeIndex tz-aware, avec colonnes :

        - ``temperature_2m`` : température air à 2 m, en K.
        - ``humidite_relative`` : humidité relative, fraction 0-1.
        - ``vitesse_vent_10m`` : vent à 10 m, en m s⁻¹.
        - ``rayonnement_global`` : rayonnement solaire incident en J m⁻² h⁻¹.
    latitude :
        Latitude du site (degrés décimaux WGS84, positif Nord).
    longitude :
        Longitude du site (degrés décimaux WGS84, positif Est).
    altitude :
        Altitude du site (m).

    Returns
    -------
    pd.Series
        ET₀ horaire (mm h⁻¹), même index que ``df``.
    """
    # `country_timezones` est un mapping {pays: [fuseaux]} ; on prend le
    # premier fuseau pour la France métropolitaine ('Europe/Paris').
    tz = pytz.country_timezones["FR"][0]
    site = location.Location(latitude, longitude, altitude=altitude, tz=tz)

    # Pression de vapeur saturante (kPa) — Eq. 11 FAO 56 / Eq. 6 V&B 2012.
    es = 0.6108 * np.exp(17.27 * (df["temperature_2m"] - 273.15) / (df["temperature_2m"] - 35.85))

    # Pente Δ de la courbe de pression de vapeur (kPa K⁻¹) — Eq. 13 FAO 56.
    delta = 4098.0 * es / (df["temperature_2m"] - 35.85) ** 2

    # Pression atmosphérique standard fonction de l'altitude (kPa) —
    # Eq. 7 FAO 56.
    pression = 101.3 * ((293.0 - 0.0065 * site.altitude) / 293.0) ** 5.26

    # Constante psychrométrique γ (kPa K⁻¹) — Eq. 8 FAO 56.
    gamma = FACTEUR_GAMMA * pression

    # Pression de vapeur effective eₑ = es · HR (kPa) — Eq. 14 FAO 56.
    ee = es * df["humidite_relative"]

    # Rayonnement net R_n = R_ns − R_nl (MJ m⁻² h⁻¹) — Eq. 40 FAO 56.
    r_ns = calcul_rayonnement_net_ondes_courtes(df)
    r_nl, zenith = calcul_rayonnement_net_ondes_longues(df, ee, site)
    r_n = r_ns - r_nl

    # Flux de chaleur dans le sol G (Eq. 45-46 FAO 56) :
    # jour (zenith < 90°) → 0.1·R_n ; nuit → 0.5·R_n.
    g_sol = (0.1 * r_n).where(zenith < 90.0, 0.5 * r_n)

    # Vent à 2 m via la fonction logarithmique standard (Eq. 47 FAO 56).
    u2 = df["vitesse_vent_10m"] * 4.87 / np.log(67.8 * 10 - 5.42)

    # ET₀ horaire (mm h⁻¹) — Eq. 53 FAO 56 décomposée en composantes
    # radiative + aérodynamique pour clamp ≥ 0.
    denominateur = delta + gamma * (1.0 + 0.34 * u2)
    etp1 = np.maximum(0, delta * (r_n - g_sol) / LAMBDA / denominateur)
    etp2 = np.maximum(0, gamma * 37.0 / df["temperature_2m"] * u2 * (es - ee) / denominateur)
    return etp1 + etp2
