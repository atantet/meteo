"""Tendance jour/nuit × N j × 2 modèles pour le dashboard App 2.

Agrège une prévision horaire Open-Meteo en cellules « fenêtre × jour »,
chaque cellule portant les variables agrégées attendues par la grille
de tendance :

- ``code_picto`` (weather_code dominant)
- ``libelle`` (label texte du code dominant)
- ``t_mean`` et ``t_extreme`` (T_max pour la fenêtre « jour », T_min pour
  la fenêtre « nuit »)
- ``pluie_mm`` (cumul de la fenêtre)
- ``prob_pluie_pct`` (max de la fenêtre)
- ``vent_moy_kmh`` (moyenne sur la fenêtre, conversion m/s → km/h)
- ``rafales_max_kmh`` (max de la fenêtre)
- ``direction_cardinal`` (vecteur moyen pondéré vitesse, en secteur 8)

Vu côté UI, deux modèles (ARPEGE court terme + ECMWF moyen terme) sont
empilés en 4 lignes : ARPEGE jour, ARPEGE nuit, ECMWF jour, ECMWF nuit ;
les colonnes sont les jours civils.

Convention « jour » / « nuit » (v0) :
- ``jour`` : heures locales [FENETRE_JOUR_DEBUT, FENETRE_JOUR_FIN)
- ``nuit`` : heures locales [0, FENETRE_JOUR_DEBUT) ∪ [FENETRE_JOUR_FIN, 24)

La nuit du jour civil J est donc la **soirée + matinée du même jour J**
local — pas la nuit calendaire J-1 → J. Ce choix garde l'agrégation
bornée à un jour civil, simple à indexer ; on perd un peu de fidélité
sémantique (mélange soir J et nuit J) mais c'est cohérent avec la
granularité « 1 colonne par jour » de la grille.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from apps.shared.pictograms import code_dominant_fenetre
from apps.shared.pictograms import libelle as libelle_picto

# Fenêtre jour : 7 h ≤ h < 19 h local (12 h). Le reste est « nuit ».
FENETRE_JOUR_DEBUT = 7
FENETRE_JOUR_FIN = 19

FENETRE_JOUR = "jour"
FENETRE_NUIT = "nuit"

# Conversion vent : Open-Meteo livre en m/s (cf. socle), grille affiche km/h.
MS_VERS_KMH = 3.6

# Conversion T° : socle Open-Meteo stocke en K (+ 273.15 à l'ingestion,
# cf. `meteo_socle.sources.openmeteo`). La grille affiche en °C.
KELVIN_VERS_CELSIUS = 273.15

# Nombre minimal d'heures couvertes par fenêtre pour créer une cellule.
# Évite l'effet "1 heure de couverture" en fin d'horizon ARPEGE (où le
# décalage UTC fait déborder 1 ou 2 heures sur un jour local supplémentaire,
# affichées comme une cellule complète tout en n'étant pas représentatives).
MIN_HEURES_PAR_FENETRE = 4

# Secteurs cardinaux 8 directions (N, NE, E, SE, S, SO, O, NO).
_CARDINAUX = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


@dataclass(frozen=True)
class CelluleFenetre:
    """Variables agrégées sur une fenêtre (jour OU nuit) d'un jour civil."""

    code_picto: int | None
    libelle_picto: str
    t_mean: float
    t_extreme: float  # t_max si « jour », t_min si « nuit »
    pluie_mm: float
    prob_pluie_pct: float
    vent_moy_kmh: float
    rafales_max_kmh: float
    direction_cardinal: str
    direction_deg: float
    etp_mm: float  # cumul ETP socle FAO sur la fenêtre, NaN si non fourni


def _direction_cardinal(deg: float) -> str:
    """Convertit un cap (degrés, 0=N, sens horaire) en secteur cardinal 8."""
    if pd.isna(deg):
        return ""
    idx = int(round((deg % 360) / 45)) % 8
    return _CARDINAUX[idx]


def _direction_moyenne_ponderee(group: pd.DataFrame) -> float:
    """Moyenne vectorielle pondérée par la vitesse (cap dominant en degrés).

    Convention météo : les angles sont les *caps d'origine* du vent (0 = N
    venant du nord). On somme les vecteurs (-sin θ, -cos θ) pondérés par
    la vitesse, puis on reprojette en angle. Sans vitesse, poids unitaire.
    """
    if "direction_vent_deg" not in group.columns or group.empty:
        return float("nan")
    s = group["direction_vent_deg"].dropna()
    if s.empty:
        return float("nan")
    rad = np.deg2rad(s)
    if "vitesse_vent_10m" in group.columns:
        poids = group.loc[s.index, "vitesse_vent_10m"].fillna(0.0)
    else:
        poids = pd.Series(1.0, index=s.index)
    u = -poids * np.sin(rad)
    v = -poids * np.cos(rad)
    return float(np.rad2deg(np.arctan2(-u.mean(), -v.mean())) % 360)


def _masque_fenetre(index: pd.DatetimeIndex, jour: pd.Timestamp, fenetre: str) -> np.ndarray:
    """Masque booléen pour la fenêtre demandée sur le jour civil ``jour``.

    ``index`` doit être tz-aware sur la zone locale (heures lues directement).
    ``jour`` est attendu à minuit local, même tz que ``index``.
    """
    base = np.asarray(index.normalize() == jour)
    heure = np.asarray(index.hour)
    if fenetre == FENETRE_JOUR:
        plage = (heure >= FENETRE_JOUR_DEBUT) & (heure < FENETRE_JOUR_FIN)
    else:  # nuit = complément du jour, borné au jour civil
        plage = (heure < FENETRE_JOUR_DEBUT) | (heure >= FENETRE_JOUR_FIN)
    return base & plage


def _agreger_cellule(
    group: pd.DataFrame,
    fenetre: str,
    etp_fenetre: pd.Series | None = None,
) -> CelluleFenetre:
    """Agrège un sous-DataFrame horaire (déjà filtré sur une fenêtre).

    La T° est convertie K → °C : la socle Open-Meteo stocke en kelvin
    (+ 273.15 à l'ingestion), mais l'utilisateur lit des °C.
    ``etp_fenetre`` est une série ETP horaire (mm/h) déjà filtrée sur
    la même fenêtre ; sa somme donne l'ETP cumulée de la fenêtre.
    """
    t_k = group.get("temperature_2m")
    t_c = (t_k - KELVIN_VERS_CELSIUS) if t_k is not None else None
    t_mean = float(t_c.mean()) if t_c is not None and not t_c.empty else float("nan")
    if fenetre == FENETRE_JOUR:
        t_extreme = float(t_c.max()) if t_c is not None and not t_c.empty else float("nan")
    else:
        t_extreme = float(t_c.min()) if t_c is not None and not t_c.empty else float("nan")

    pluie_mm = (
        float(group["precipitation"].sum()) if "precipitation" in group.columns else float("nan")
    )
    prob = group.get("probabilite_pluie_pct")
    prob_max = float(prob.max()) if prob is not None and not prob.dropna().empty else float("nan")

    vent_ms = group.get("vitesse_vent_10m")
    vent_moy_kmh = (
        float(vent_ms.mean() * MS_VERS_KMH)
        if vent_ms is not None and not vent_ms.dropna().empty
        else float("nan")
    )
    raf_ms = group.get("rafales_vent_10m")
    rafales_max_kmh = (
        float(raf_ms.max() * MS_VERS_KMH)
        if raf_ms is not None and not raf_ms.dropna().empty
        else float("nan")
    )

    direction_deg = _direction_moyenne_ponderee(group)

    code = code_dominant_fenetre(group["weather_code"]) if "weather_code" in group.columns else None
    lib = libelle_picto(code) if code is not None else ""

    etp_mm = (
        float(etp_fenetre.dropna().sum())
        if etp_fenetre is not None and not etp_fenetre.dropna().empty
        else float("nan")
    )

    return CelluleFenetre(
        code_picto=code,
        libelle_picto=lib,
        t_mean=t_mean,
        t_extreme=t_extreme,
        pluie_mm=pluie_mm,
        prob_pluie_pct=prob_max,
        vent_moy_kmh=vent_moy_kmh,
        rafales_max_kmh=rafales_max_kmh,
        direction_cardinal=_direction_cardinal(direction_deg),
        direction_deg=direction_deg,
        etp_mm=etp_mm,
    )


def agreger_par_fenetre(
    horaire: pd.DataFrame,
    tz_locale: str = "Europe/Paris",
    horizon_jours: int | None = None,
    etp_horaire: pd.Series | None = None,
) -> dict[tuple[pd.Timestamp, str], CelluleFenetre]:
    """Agrège la prévision horaire en cellules (date locale, fenêtre).

    Parameters
    ----------
    horaire :
        DataFrame indexé tz-aware UTC, colonnes selon les conventions
        socle (cf. ``OpenMeteoForecast``).
    tz_locale :
        Fuseau de présentation (par défaut Europe/Paris).
    horizon_jours :
        Si fourni, plafonne au nombre de jours locaux couverts.
    etp_horaire :
        Série ETP horaire (mm/h) socle FAO calculée en amont, indexée
        tz-aware UTC. Si fournie, chaque cellule porte la somme ETP de
        sa fenêtre ; sinon `etp_mm` reste à NaN.

    Returns
    -------
    dict
        Clé = ``(jour_local_minuit, fenetre)`` où ``fenetre`` ∈
        {"jour", "nuit"} ; valeur = ``CelluleFenetre`` agrégée.
        Les fenêtres couvertes par moins de
        ``MIN_HEURES_PAR_FENETRE`` heures sont écartées pour éviter
        l'affichage de cellules peu représentatives.
    """
    if horaire.empty:
        return {}

    df = horaire.copy()
    df.index = pd.DatetimeIndex(df.index).tz_convert(tz_locale)

    etp_loc = None
    if etp_horaire is not None and not etp_horaire.empty:
        etp_loc = etp_horaire.copy()
        etp_loc.index = pd.DatetimeIndex(etp_loc.index).tz_convert(tz_locale)

    jours_uniques = pd.DatetimeIndex(df.index).normalize().unique().sort_values()
    if horizon_jours is not None:
        jours_uniques = jours_uniques[:horizon_jours]

    cellules: dict[tuple[pd.Timestamp, str], CelluleFenetre] = {}
    for jour in jours_uniques:
        for fenetre in (FENETRE_JOUR, FENETRE_NUIT):
            masque = _masque_fenetre(df.index, jour, fenetre)
            if int(masque.sum()) < MIN_HEURES_PAR_FENETRE:
                continue
            etp_fenetre = None
            if etp_loc is not None:
                masque_etp = _masque_fenetre(etp_loc.index, jour, fenetre)
                etp_fenetre = etp_loc.loc[masque_etp]
            cellules[(jour, fenetre)] = _agreger_cellule(df.loc[masque], fenetre, etp_fenetre)

    return cellules
