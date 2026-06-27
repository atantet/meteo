# libmeteo_socle — temps sensible (« weather symbol ») dérivé des champs modèle.
#
# Ce module est un PORTAGE Python de l'algorithme de symbole temps de
# l'Institut météorologique norvégien (MET Norway / met.no), publié sous
# GPL :
#
#     libweather_symbol — Copyright (C) 2014 met.no
#     https://github.com/metno/weather_symbol  (GPL-2.0-or-later)
#
# Conformément à la GPL, ce dérivé est lui aussi distribué sous licence
# GPL (v3 ou ultérieure, cf. fichier LICENSE à la racine). Le crédit
# revient à MET Norway pour la logique de classification (seuils de
# nébulosité, paliers de précipitation, phase pluie/neige). Les ajouts
# propres à ce dépôt (reconstruction de la nébulosité totale depuis les
# couches basse/moyenne/haute, dérivation orage depuis la CAPE, brouillard
# depuis l'humidité, et la projection vers les codes WMO 4677) sont
# explicitement signalés ci-dessous.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
"""Temps sensible (« weather symbol ») dérivé des champs d'un modèle.

Motivation
----------

L'API *Single Runs* d'Open-Meteo ne fournit **aucun** ``weather_code`` pour
AROME France HD (0/72 h vérifié). Dans la fusion App 1, le code était donc
comblé par ARPEGE, alors que la pluie venait d'AROME : deux modèles
différents sur la même ligne → pictogramme « pluie » avec cumul AROME nul
(cas vendredi 05/06/2026). Pour rétablir la cohérence picto ↔ cumul, on
**fabrique** le code temps à partir des **champs AROME eux-mêmes**.

Plutôt que d'inventer des seuils, on suit une méthodologie **lisible,
ouverte et opérée par un service météo national** : l'algorithme de symbole
de MET Norway (yr.no). L'ECMWF, lui, ne publie pas d'algorithme réutilisable
(ses météogrammes sont des box-plots). Cf. ADR-0013.

Algorithme MET Norway (porté fidèlement, cf. ``weather_symbol/src/Factory.cpp``)
-------------------------------------------------------------------------------

1. **Nébulosité** (% → indice 0-3) :
   ``≤13`` → 0 (clair) · ``≤38`` → 1 (peu nuageux) · ``≤86`` → 2 (partiellement
   nuageux) · ``>86`` → 3 (couvert).
2. **Précipitation** (mm cumulés sur ``hours`` → gouttes 0-3) : paliers
   interpolés linéairement entre la fenêtre 1 h ``{0.1, 0.25, 0.95}`` et la
   fenêtre 6 h ``{0.5, 0.95, 4.95}``.
3. **Réduction « nuages hauts »** : sans pluie ni brouillard, si les couches
   basse et moyenne sont dégagées (≤ 13 %), le ciel est dominé par les seuls
   cirrus → ramené à « ensoleillé » (cirrus transparent ; MF confirme sur 30,
   50, 80 et 95 % de recouvrement total, 4 jours 2026-06-21→24).
4. **Averse vs pluie continue** : sous un ciel couvert (indice 3) la
   précipitation est *continue* ; sous un ciel partiel elle est en *averses*
   (variantes « Sun » de MET Norway).
5. **Phase** (pluie / neige fondue / neige) selon la température :
   ``≤0.5 °C`` → neige · ``≤1.5 °C`` → neige fondue · sinon pluie.

Ajouts propres à ce dépôt (signalés, à valider terrain — cf. principe
« vérifier les substitutions »)
-----------------------------------------------------------------------

- **Nébulosité totale** : AROME ne renvoie pas ``cloud_cover`` total
  (0/72 h) mais les trois couches. On reconstruit en supposant un
  recouvrement aléatoire : ``total = 1 − (1−bas)(1−moy)(1−haut)``.
- **Orage** : MET Norway prend un booléen ``thunder`` (champ propre). On le
  dérive de la CAPE (``≥ CAPE_SEUIL_ORAGE_JKG`` **et** précipitation
  présente). Seuil **provisoire**.
- **Brouillard** : ``visibility`` est indisponible (0/72 h). Proxy par
  l'humidité relative élevée sans précipitation. Seuil **provisoire**.
- **Projection WMO 4677** : MET Norway a son propre vocabulaire de symboles ;
  on le projette sur la table de code OMM 4677 utilisée par ``pictograms.py``
  (la neige fondue, sans icône OMM dédiée, est rendue comme de la neige ;
  l'orage est rendu par le code 95 sans distinction d'intensité).

Références
----------

- MET Norway, *weather_symbol* (libweather_symbol), 2014.
  <https://github.com/metno/weather_symbol> — GPL-2.0-or-later.
- OMM, *Manuel des codes*, table de code 4677 (ww, temps présent).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --- Seuils MET Norway (portés depuis Factory.cpp) ---------------------------

# Nébulosité (% de couverture) → indice 0 (clair) … 3 (couvert).
_SEUILS_NEBULOSITE_PCT = (13.0, 38.0, 86.0)

# Paliers de précipitation aux fenêtres 1 h et 6 h (mm). Pour une fenêtre de
# ``hours`` heures, chaque palier est interpolé linéairement entre les deux.
_PALIERS_PLUIE_1H = (0.1, 0.25, 0.95)
_PALIERS_PLUIE_6H = (0.5, 0.95, 4.95)

# Phase (température de l'air, °C) : bornes neige / neige fondue.
_SEUIL_NEIGE_C = 0.5
_SEUIL_NEIGE_FONDUE_C = 1.5

# --- Seuils propres à ce dépôt (provisoires, à valider terrain) --------------

#: CAPE minimale (J/kg) pour signaler l'orage quand il pleut. Provisoire.
CAPE_SEUIL_ORAGE_JKG = 200.0
#: Humidité relative (fraction) au-delà de laquelle on signale le brouillard
#: en l'absence de précipitation (proxy faute de ``visibility``). Provisoire.
RH_SEUIL_BROUILLARD = 0.97

# --- Vocabulaire de symboles (sous-ensemble « base » de MET Norway) ----------
# On n'a pas besoin des variantes jour/nuit (« Dark_… ») : la nuit est gérée
# en aval par ``pictograms.icone_base64(code, nuit=…)``.

_KEY_FOG = "Fog"
_NEBULOSITE_VERS_SYMBOLE = {0: "Sun", 1: "LightCloud", 2: "PartlyCloud", 3: "Cloud"}


def _nebulosite(cloud_cover_pct: float) -> int:
    """Indice de nébulosité 0-3 depuis un pourcentage de couverture (0-100)."""
    if cloud_cover_pct <= _SEUILS_NEBULOSITE_PCT[0]:
        return 0
    if cloud_cover_pct <= _SEUILS_NEBULOSITE_PCT[1]:
        return 1
    if cloud_cover_pct <= _SEUILS_NEBULOSITE_PCT[2]:
        return 2
    return 3


def _paliers_pluie(hours: int) -> list[float]:
    """Paliers de précipitation [0, p1, p2, p3] (mm) pour une fenêtre ``hours``.

    Reproduit ``precipitation_limits`` de MET Norway : interpolation linéaire
    entre la fenêtre 1 h et la fenêtre 6 h (pas de 1/5 par heure).
    """
    if hours < 1 or hours > 6:
        raise ValueError("La fenêtre de symbole doit faire entre 1 et 6 heures.")
    paliers = [0.0]
    for bas, haut in zip(_PALIERS_PLUIE_1H, _PALIERS_PLUIE_6H, strict=True):
        pas = (haut - bas) / 5.0
        paliers.append(bas + pas * (hours - 1))
    return paliers


def _gouttes(precipitation_mm: float, hours: int) -> int:
    """Indice d'intensité de précipitation 0-3 (cumul ``precipitation_mm``)."""
    if precipitation_mm < 0:
        raise ValueError("La précipitation ne peut être négative.")
    paliers = _paliers_pluie(hours)
    for niveau in range(3, -1, -1):
        if precipitation_mm >= paliers[niveau]:
            return niveau
    return 0


def _phase(temperature_c: float) -> int:
    """Phase de précipitation : 0 pluie, 1 neige fondue, 2 neige (temp. air)."""
    if temperature_c <= _SEUIL_NEIGE_C:
        return 2
    if temperature_c <= _SEUIL_NEIGE_FONDUE_C:
        return 1
    return 0


def symbole_metno(
    cloud_cover_pct: float,
    precipitation_mm: float,
    *,
    hours: int = 1,
    temperature_c: float = 10.0,
    thunder: bool = False,
    fog: bool = False,
    low_cloud_pct: float | None = None,
    mid_cloud_pct: float | None = None,
    max_precipitation_mm: float | None = None,
    phase: int | None = None,
) -> str:
    """Symbole temps MET Norway (chaîne du vocabulaire « base »).

    Portage fidèle de ``Factory::getSymbol(const WeatherData&)``. Retourne un
    nom de symbole (ex. ``"PartlyCloud"``, ``"LightRainSun"``, ``"HeavySnow"``,
    ``"RainThunder"``, ``"Fog"``).

    Parameters
    ----------
    cloud_cover_pct :
        Nébulosité totale en pourcentage (0-100).
    precipitation_mm :
        Précipitation cumulée sur la fenêtre ``hours`` (mm).
    hours :
        Longueur de la fenêtre d'agrégation (1-6 h) — fixe les paliers de pluie.
    temperature_c :
        Température de l'air (°C), pour la phase pluie/neige.
    thunder, fog :
        Drapeaux orage / brouillard (dérivés en amont pour nos données).
    low_cloud_pct, mid_cloud_pct :
        Couches basse et moyenne (%), pour la réduction « nuages hauts ».
    max_precipitation_mm :
        Précipitation maximale attendue (incertitude) ; remonte un ciel peu
        nuageux à « partiellement nuageux » s'il peut pleuvoir.
    """
    nebulosite = _nebulosite(cloud_cover_pct)
    gouttes = _gouttes(precipitation_mm, hours)

    # Réduction « nuages hauts » : sans pluie ni brouillard, si bas + moyen ≤ 13 %,
    # le ciel est dominé par les seuls cirrus → **ensoleillé** (cirrus transparent).
    # MF rend ces ciels « dégagé/ensoleillé » quel que soit le recouvrement total
    # (30, 50, 80, 95 % → MF dégagé, biais confirmé 4 jours 2026-06-21→24).
    if (
        nebulosite >= 1
        and gouttes == 0
        and not fog
        and low_cloud_pct is not None
        and mid_cloud_pct is not None
        and _nebulosite(low_cloud_pct) == 0
        and _nebulosite(mid_cloud_pct) == 0
    ):
        nebulosite = 0

    # Possibilité de pluie : remonte un ciel dégagé à partiellement nuageux.
    if max_precipitation_mm is not None and max_precipitation_mm > 0.1 and nebulosite < 2:
        nebulosite = 2

    is_thunder = thunder and gouttes > 0
    is_fog = fog and gouttes == 0
    if is_fog:
        return _KEY_FOG

    if gouttes == 0:
        return _NEBULOSITE_VERS_SYMBOLE[nebulosite]

    # Phase : pilotée par le type de précip MF (``phase`` fourni, ADR-0021) ou, à
    # défaut, par la température (heuristique MET Norway d'origine).
    phase = phase if phase is not None else _phase(temperature_c)
    couvert = nebulosite == 3  # couvert → pluie continue ; sinon → averses

    # Famille de base selon l'intensité (1-3) et continu/averse.
    if couvert:
        base = {1: "Drizzle", 2: "LightRain", 3: "Rain"}[gouttes]
    else:
        base = {1: "DrizzleSun", 2: "LightRainSun", 3: "RainSun"}[gouttes]

    symbole = _appliquer_phase(base, phase)
    if is_thunder:
        symbole = _SYMBOLE_VERS_ORAGE[symbole]
    return symbole


# Table phase : (famille pluie) → variante neige fondue (1) / neige (2).
# Portée depuis ``Factory::initCodeTable_`` (variantes [1] et [2]).
_PHASE_NEIGE_FONDUE = {
    "Drizzle": "LightSleet",
    "LightRain": "Sleet",
    "Rain": "HeavySleet",
    "DrizzleSun": "LightSleetSun",
    "LightRainSun": "SleetSun",
    "RainSun": "HeavySleetSun",
}
_PHASE_NEIGE = {
    "Drizzle": "LightSnow",
    "LightRain": "Snow",
    "Rain": "HeavySnow",
    "DrizzleSun": "LightSnowSun",
    "LightRainSun": "SnowSun",
    "RainSun": "HeavySnowSun",
}


def _appliquer_phase(base_pluie: str, phase: int) -> str:
    """Applique la phase (0 pluie / 1 neige fondue / 2 neige) à une famille."""
    if phase == 1:
        return _PHASE_NEIGE_FONDUE[base_pluie]
    if phase == 2:
        return _PHASE_NEIGE[base_pluie]
    return base_pluie


# Toute précipitation peut prendre une variante orage. On mappe vers le
# symbole « …Thunder » correspondant (suffixe), en conservant la racine.
_SYMBOLE_VERS_ORAGE = {
    "Drizzle": "DrizzleThunder",
    "LightRain": "LightRainThunder",
    "Rain": "RainThunder",
    "DrizzleSun": "DrizzleThunderSun",
    "LightRainSun": "LightRainThunderSun",
    "RainSun": "RainThunderSun",
    "LightSleet": "LightSleetThunder",
    "Sleet": "SleetThunder",
    "HeavySleet": "HeavySleetThunder",
    "LightSleetSun": "LightSleetThunderSun",
    "SleetSun": "SleetSunThunder",
    "HeavySleetSun": "HeavySleetThunderSun",
    "LightSnow": "LightSnowThunder",
    "Snow": "SnowThunder",
    "HeavySnow": "HeavySnowThunder",
    "LightSnowSun": "LightSnowThunderSun",
    "SnowSun": "SnowSunThunder",
    "HeavySnowSun": "HeavySnowThunderSun",
}


# --- Projection vers la table OMM 4677 (ajout propre à ce dépôt) -------------
# Choix : pluie continue → 61/63/65 ; averses → 80/81/82 ; neige → 71/73/75 ;
# averses de neige → 85/86 ; neige fondue continue → neige (71/73/75) ;
# averses de neige fondue → 68/69/70 (icônes yr dédiées) ; orage → 95.
_SYMBOLE_VERS_WMO: dict[str, int] = {
    "Sun": 0,
    "LightCloud": 1,
    "PartlyCloud": 2,
    "Cloud": 3,
    "Fog": 45,
    # Pluie continue (ciel couvert).
    "Drizzle": 61,
    "LightRain": 63,
    "Rain": 65,
    # Averses (ciel partiel).
    "DrizzleSun": 80,
    "LightRainSun": 81,
    "RainSun": 82,
    # Neige continue.
    "LightSnow": 71,
    "Snow": 73,
    "HeavySnow": 75,
    # Averses de neige.
    "LightSnowSun": 85,
    "SnowSun": 86,
    "HeavySnowSun": 86,
    # Neige fondue continue → rendue comme neige (pas d'icône continue dédiée).
    "LightSleet": 71,
    "Sleet": 73,
    "HeavySleet": 75,
    # Averses de neige fondue → codes 68/69/70 avec icônes yr jour/nuit.
    "LightSleetSun": 68,
    "SleetSun": 69,
    "HeavySleetSun": 70,
}

#: Code OMM 4677 de l'orage (toutes variantes « …Thunder » y sont ramenées).
WMO_ORAGE = 95


def metno_vers_wmo(symbole: str) -> int:
    """Projette un symbole MET Norway sur un code OMM 4677 (cf. tableau)."""
    if symbole.endswith("Thunder") or symbole.endswith("ThunderSun"):
        return WMO_ORAGE
    return _SYMBOLE_VERS_WMO[symbole]


def code_temps_wmo(
    cloud_cover_pct: float,
    precipitation_mm: float,
    **kwargs: object,
) -> int:
    """Code OMM 4677 dérivé (raccourci ``metno_vers_wmo(symbole_metno(...))``)."""
    symbole = symbole_metno(cloud_cover_pct, precipitation_mm, **kwargs)  # type: ignore[arg-type]
    return metno_vers_wmo(symbole)


def nebulosite_totale_pct(
    low: float | pd.Series,
    mid: float | pd.Series,
    high: float | pd.Series,
) -> float | pd.Series:
    """Nébulosité totale (%) par recouvrement aléatoire des trois couches.

    ``total = 1 − (1−bas)(1−moy)(1−haut)``. Entrées en **fraction** (0-1),
    sortie en **pourcentage** (0-100). Ajout propre à ce dépôt : AROME ne
    fournit pas ``cloud_cover`` total mais les trois couches.
    """
    return (1.0 - (1.0 - low) * (1.0 - mid) * (1.0 - high)) * 100.0


# Colonnes socle nécessaires au calcul (unités socle : fractions, K, mm, J/kg).
_COLS_AROME_TEMPS = (
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "precipitation",
    "temperature_2m",
)


def serie_code_temps(df: pd.DataFrame, hours: int = 1) -> pd.Series:
    """Série horaire de codes OMM 4677 dérivés des champs AROME d'un DataFrame.

    Attend des colonnes aux **noms et unités socle** : ``cloud_cover_low/mid/
    high`` (fraction 0-1), ``precipitation`` (mm), ``temperature_2m`` (K), et
    en option ``cape`` (J/kg) et ``humidite_relative`` (fraction). Renvoie une
    ``Series`` de codes (``Int64`` avec ``<NA>`` là où les champs requis
    manquent — typiquement la queue ARPEGE au-delà de l'horizon AROME).
    """
    manquantes = [c for c in _COLS_AROME_TEMPS if c not in df.columns]
    if manquantes:
        raise KeyError(f"serie_code_temps : colonnes socle manquantes {manquantes}")

    n = len(df)
    ccl = df["cloud_cover_low"].to_numpy(dtype=float)
    ccm = df["cloud_cover_mid"].to_numpy(dtype=float)
    cch = df["cloud_cover_high"].to_numpy(dtype=float)
    precip = df["precipitation"].to_numpy(dtype=float)
    temp_c = df["temperature_2m"].to_numpy(dtype=float) - 273.15
    cape = df["cape"].to_numpy(dtype=float) if "cape" in df.columns else np.full(n, np.nan)
    rh = (
        df["humidite_relative"].to_numpy(dtype=float)
        if "humidite_relative" in df.columns
        else np.full(n, np.nan)
    )

    codes: list[int | None] = []
    for i in range(n):
        if np.isnan(ccl[i]) or np.isnan(ccm[i]) or np.isnan(cch[i]) or np.isnan(precip[i]):
            codes.append(None)
            continue
        thunder = bool((not np.isnan(cape[i])) and cape[i] >= CAPE_SEUIL_ORAGE_JKG)
        fog = bool((not np.isnan(rh[i])) and rh[i] >= RH_SEUIL_BROUILLARD)
        total_pct = (1.0 - (1.0 - ccl[i]) * (1.0 - ccm[i]) * (1.0 - cch[i])) * 100.0
        codes.append(
            code_temps_wmo(
                float(total_pct),
                float(precip[i]),
                hours=hours,
                temperature_c=float(temp_c[i]),
                thunder=thunder,
                fog=fog,
                low_cloud_pct=float(ccl[i]) * 100.0,
                mid_cloud_pct=float(ccm[i]) * 100.0,
            )
        )
    return pd.Series(codes, index=df.index, dtype="Int64", name="weather_code")


def code_temps_fenetre(df: pd.DataFrame, hours: int | None = None) -> int | None:
    """Code OMM 4677 représentatif d'une FENÊTRE (sur le cumul), pas heure/heure.

    Classe la fenêtre sur le **cumul** de précipitation — donc à la **même
    échelle que le cumul affiché** — avec les paliers de pluie de la **durée**
    de la fenêtre (MET Norway, 1-6 h). Évite qu'un seul pic horaire fasse
    basculer le picto en « pluie forte » alors que le cumul sur la fenêtre reste
    modéré.

    Agrégations sur la fenêtre : précipitation = **somme** (cumul) ; nébulosité
    et température = **moyenne** (phase, averse/continu) ; CAPE et humidité =
    **max** (signaler un orage / un brouillard survenu dans la fenêtre). Renvoie
    ``None`` si la fenêtre est vide ou si les champs AROME manquent (queue
    ARPEGE hors horizon) — l'appelant peut alors retomber sur le code horaire.
    """
    if df.empty or any(c not in df.columns for c in _COLS_AROME_TEMPS):
        return None
    sub = df.dropna(subset=list(_COLS_AROME_TEMPS))
    if sub.empty:
        return None
    n = len(sub) if hours is None else hours
    n = max(1, min(6, n))

    low = sub["cloud_cover_low"]
    mid = sub["cloud_cover_mid"]
    high = sub["cloud_cover_high"]
    total_pct = float(((1.0 - (1.0 - low) * (1.0 - mid) * (1.0 - high)) * 100.0).mean())

    cape_max = float(sub["cape"].max()) if "cape" in sub.columns else float("nan")
    rh_max = (
        float(sub["humidite_relative"].max())
        if "humidite_relative" in sub.columns
        else float("nan")
    )
    thunder = (not pd.isna(cape_max)) and cape_max >= CAPE_SEUIL_ORAGE_JKG
    fog = (not pd.isna(rh_max)) and rh_max >= RH_SEUIL_BROUILLARD

    return code_temps_wmo(
        total_pct,
        float(sub["precipitation"].sum()),
        hours=n,
        temperature_c=float(sub["temperature_2m"].mean()) - 273.15,
        thunder=bool(thunder),
        fog=bool(fog),
        low_cloud_pct=float(low.mean()) * 100.0,
        mid_cloud_pct=float(mid.mean()) * 100.0,
    )


# ===========================================================================
# Picto piloté par les DIAGNOSTICS MF (ADR-0021) — chemin privilégié quand on
# a AROME/ECMWF direct : phase ← type de précip (PTYPE, pas la T° heuristique),
# brouillard ← visibilité (pas le proxy HR), **orage jamais dérivé** (Vigilance).
# Module ravivé (dé-déprécié, cf. ADR-0013) pour servir ce chemin.
# ===========================================================================

#: Type de précip → phase. Codes GRIB 4.201 (0 = aucune, vérifié au point ;
#: les autres à confirmer sur un run humide, deferral ADR-0021).
_PTYPE_NEIGE = frozenset({5, 9})  # neige, granules de neige roulée
_PTYPE_FONDUE = frozenset({4, 6, 7, 8})  # glace/mélange, neige mouillée, pluie+neige, grésil
_PTYPE_VERGLAS = frozenset({3, 12})  # pluie / bruine verglaçante
#: Visibilité (m) sous laquelle on signale le brouillard (seuil OMM brouillard).
VISI_SEUIL_BROUILLARD_M = 1000.0
#: Pluie verglaçante (OMM) : légère / forte.
WMO_VERGLAS_LEGER, WMO_VERGLAS_FORT = 66, 67


def phase_depuis_ptype(code: float) -> str:
    """Type de précip MF (code GRIB) → phase : ``rain`` / ``sleet`` / ``snow`` / ``verglas``.

    Inconnu / NaN / 0 (aucune) / 1 (pluie) / 2 (orage : phase pluie, l'orage relève de
    la Vigilance, pas du picto) / 11 (bruine) → ``rain``.
    """
    if pd.isna(code):
        return "rain"
    c = int(round(code))
    if c in _PTYPE_VERGLAS:
        return "verglas"
    if c in _PTYPE_NEIGE:
        return "snow"
    if c in _PTYPE_FONDUE:
        return "sleet"
    return "rain"


_PHASE_VERS_INDICE = {"rain": 0, "sleet": 1, "snow": 2}


def code_wmo_diagnostic(
    cloud_cover_frac: float,
    precipitation_mm: float,
    type_precip_code: float,
    visibilite_m: float = float("nan"),
    *,
    hours: int = 1,
    low_cloud_frac: float | None = None,
    mid_cloud_frac: float | None = None,
) -> int:
    """Code OMM 4677 depuis les diagnostics MF (phase PTYPE, brouillard visibilité).

    ``cloud_cover_frac`` et couches en **fraction 0-1**, pluie en **mm**,
    ``type_precip_code`` = code GRIB, ``visibilite_m`` en **mètres** (NaN si absent).
    Pas d'orage (Vigilance). Pluie verglaçante → 66/67 ; brouillard (visi basse, sec)
    → 45 ; sinon vocabulaire MET Norway avec phase forcée par PTYPE.
    """
    sec = pd.isna(precipitation_mm) or precipitation_mm < 0.1
    if not pd.isna(visibilite_m) and visibilite_m < VISI_SEUIL_BROUILLARD_M and sec:
        return 45  # brouillard (givrant 48 non distingué en v0)
    phase = phase_depuis_ptype(type_precip_code)
    if phase == "verglas" and not sec:
        return WMO_VERGLAS_FORT if precipitation_mm >= 2.5 else WMO_VERGLAS_LEGER
    return code_temps_wmo(
        cloud_cover_frac * 100.0,
        precipitation_mm,
        hours=hours,
        thunder=False,
        fog=False,
        phase=_PHASE_VERS_INDICE[phase if phase != "verglas" else "rain"],
        low_cloud_pct=None if low_cloud_frac is None else low_cloud_frac * 100.0,
        mid_cloud_pct=None if mid_cloud_frac is None else mid_cloud_frac * 100.0,
    )


def serie_code_temps_mf(df: pd.DataFrame, hours: int = 1) -> pd.Series:
    """Série OMM 4677 depuis les colonnes diagnostic MF d'un DataFrame (AROME/ECMWF).

    Requiert ``cloud_cover`` (fraction) et ``precipitation`` (mm) ; exploite si
    présentes ``type_precip`` (phase), ``visibilite_m`` (brouillard), ``cloud_cover_
    low``/``mid`` (réduction cirrus). ``<NA>`` là où ciel ou pluie manquent.
    """
    for c in ("cloud_cover", "precipitation"):
        if c not in df.columns:
            raise KeyError(f"serie_code_temps_mf : colonne socle manquante {c!r}")
    cc = df["cloud_cover"].to_numpy(dtype=float)
    pr = df["precipitation"].to_numpy(dtype=float)
    pt = (
        df["type_precip"].to_numpy(dtype=float)
        if "type_precip" in df.columns
        else np.full(len(df), np.nan)
    )
    vis = (
        df["visibilite_m"].to_numpy(dtype=float)
        if "visibilite_m" in df.columns
        else np.full(len(df), np.nan)
    )
    low = df["cloud_cover_low"].to_numpy(dtype=float) if "cloud_cover_low" in df.columns else None
    mid = df["cloud_cover_mid"].to_numpy(dtype=float) if "cloud_cover_mid" in df.columns else None
    codes: list[int | None] = []
    for i in range(len(df)):
        if np.isnan(cc[i]) or np.isnan(pr[i]):
            codes.append(None)
            continue
        codes.append(
            code_wmo_diagnostic(
                float(cc[i]),
                float(pr[i]),
                float(pt[i]),
                float(vis[i]),
                hours=hours,
                low_cloud_frac=None if low is None else float(low[i]),
                mid_cloud_frac=None if mid is None else float(mid[i]),
            )
        )
    return pd.Series(codes, index=df.index, dtype="Int64", name="weather_code")
