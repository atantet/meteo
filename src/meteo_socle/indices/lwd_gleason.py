"""Durée d'humectation foliaire (LWD) — modèle CART Gleason 1994.

Implémentation du modèle statistique d'arbre de décision binaire publié
par Gleason et al. 1994 pour estimer si une heure est *mouillée* (leaf
wet) à partir des seules variables météorologiques standards.

Cf. ADR-0005 pour la justification du choix de modèle (CART Gleason en
contrôle croisé du modèle Magarey DPD/NWP).

Référence
---------

Gleason, M.L., Taylor, S.E., Loughin, T.M., Koehler, K.J., 1994.
*Development and validation of an empirical model to estimate the
duration of dew periods*. **Plant Disease** 78, 1011-1016.

Arbre de décision implémenté
----------------------------

À partir de quatre prédicteurs (T° °C, HR %, vent m/s, et le DPD
= T − T_d où T_d est le point de rosée Magnus-Tetens) :

::

    si DPD ≤ 3.7 °C                         → MOUILLÉ
    sinon si 3.7 < DPD ≤ 7.2 °C :
        si vent < 2.5 m/s ET HR ≥ 87.8 %    → MOUILLÉ
        sinon                                → SEC
    sinon (DPD > 7.2 °C)                     → SEC

Plus une règle d'override : si une pluie a été enregistrée dans les
``heures_pluie_persistance`` heures précédentes (défaut 1 h), l'heure
est forcée à *mouillée* (la pluie elle-même mouille la feuille, le
modèle CART n'est calibré que sur la rosée).

Seuils issus du papier original (Table 1, modèle « complete »).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Seuils Gleason 1994 (Table 1, version "complete").
DPD_SEUIL_BAS = 3.7  # °C — sous lequel toujours mouillé
DPD_SEUIL_HAUT = 7.2  # °C — au-dessus duquel toujours sec
VENT_SEUIL = 2.5  # m s⁻¹ — sec si vent dépasse, sinon dépend de HR
HR_SEUIL = 0.878  # fraction (87.8 %) — seuil HR dans la zone intermédiaire DPD


def point_de_rosee_magnus_tetens(
    t_celsius: pd.Series | np.ndarray | float,
    hr_fraction: pd.Series | np.ndarray | float,
) -> pd.Series | np.ndarray | float:
    """Point de rosée (°C) par formule Magnus-Tetens.

    Parameters
    ----------
    t_celsius :
        Température de l'air en °C.
    hr_fraction :
        Humidité relative en fraction (0-1), convention socle.

    Returns
    -------
    Td en °C (même structure que les entrées).
    """
    # Constantes Magnus-Tetens (Alduchov & Eskridge 1996, légèrement
    # plus précises que la version originale).
    a = 17.625
    b = 243.04  # °C

    # Pression de vapeur saturante × HR :
    # e_s(T) = exp(a*T/(b+T)) [forme normalisée] ; on prend ln directement.
    gamma = np.log(hr_fraction) + (a * t_celsius) / (b + t_celsius)
    return (b * gamma) / (a - gamma)


def lwd_horaire_gleason(
    horaire: pd.DataFrame,
    heures_pluie_persistance: int = 1,
) -> pd.Series:
    """Applique l'arbre CART Gleason 1994 sur une série horaire.

    Parameters
    ----------
    horaire :
        DataFrame indexé temporellement (UTC ou local) avec colonnes :
        - ``temperature_2m`` (K, convention socle)
        - ``humidite_relative`` (fraction 0-1)
        - ``vitesse_vent_10m`` (m s⁻¹)
        - ``precipitation`` (mm, optionnel — sert au override pluie).
    heures_pluie_persistance :
        Nombre d'heures pendant lesquelles la feuille reste considérée
        comme mouillée après une heure de pluie. Défaut 1.

    Returns
    -------
    pd.Series
        Booléenne (``True`` = mouillé), nommée ``lwd_wet``, indexée
        comme ``horaire``.
    """
    t_celsius = horaire["temperature_2m"] - 273.15
    hr = horaire["humidite_relative"]
    vent = horaire["vitesse_vent_10m"]

    td = point_de_rosee_magnus_tetens(t_celsius, hr)
    dpd = t_celsius - td

    # Règle CART en logique vectorisée.
    wet_zone_basse = dpd <= DPD_SEUIL_BAS
    zone_intermediaire = (dpd > DPD_SEUIL_BAS) & (dpd <= DPD_SEUIL_HAUT)
    wet_intermediaire = zone_intermediaire & (vent < VENT_SEUIL) & (hr >= HR_SEUIL)
    wet = wet_zone_basse | wet_intermediaire

    # Override pluie : si pluie sur la fenêtre précédente, mouillé.
    if "precipitation" in horaire.columns:
        pluie_recente = (
            (horaire["precipitation"] > 0)
            .rolling(window=heures_pluie_persistance, min_periods=1)
            .max()
            .astype(bool)
        )
        wet = wet | pluie_recente

    wet.name = "lwd_wet"
    return wet.astype(bool)


def heures_lwd_par_jour(
    horaire: pd.DataFrame,
    tz_locale: str = "Europe/Paris",
    heures_pluie_persistance: int = 1,
) -> pd.DataFrame:
    """Agrège la sortie horaire LWD en heures cumulées par jour calendaire local.

    Parameters
    ----------
    horaire :
        DataFrame horaire UTC (cf. ``lwd_horaire_gleason``).
    tz_locale :
        Fuseau pour découper les jours (défaut Europe/Paris).
    heures_pluie_persistance :
        Cf. ``lwd_horaire_gleason``.

    Returns
    -------
    pd.DataFrame
        Indexé par date locale (sans tz), colonnes :
        - ``heures_lwd`` : nb d'heures LWD ≥ True dans la journée locale
        - ``heures_dpd_bas`` : nb d'heures où DPD ≤ seuil bas
        - ``heures_dpd_intermediaire`` : nb d'heures dans la zone DPD
          intermédiaire (utile pour le diagnostic).
    """
    if horaire.empty:
        return pd.DataFrame(columns=["heures_lwd", "heures_dpd_bas", "heures_dpd_intermediaire"])

    wet = lwd_horaire_gleason(horaire, heures_pluie_persistance=heures_pluie_persistance)

    # Statistiques diagnostiques (visibles dans le rapport climato).
    t_celsius = horaire["temperature_2m"] - 273.15
    td = point_de_rosee_magnus_tetens(t_celsius, horaire["humidite_relative"])
    dpd = t_celsius - td

    df_horaire = pd.DataFrame(
        {
            "wet": wet.astype(int),
            "dpd_bas": (dpd <= DPD_SEUIL_BAS).astype(int),
            "dpd_intermediaire": ((dpd > DPD_SEUIL_BAS) & (dpd <= DPD_SEUIL_HAUT)).astype(int),
        },
        index=horaire.index,
    )
    # Conversion à TZ locale puis agrégation jour.
    idx_loc = pd.DatetimeIndex(df_horaire.index).tz_convert(tz_locale)
    df_horaire.index = idx_loc
    quotidien = df_horaire.resample("D").sum()
    quotidien.index = pd.DatetimeIndex(quotidien.index).tz_localize(None)
    quotidien.index.name = "date"
    quotidien.columns = ["heures_lwd", "heures_dpd_bas", "heures_dpd_intermediaire"]
    return quotidien
