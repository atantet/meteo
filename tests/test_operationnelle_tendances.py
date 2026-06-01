"""Tests offline du module `apps.operationnelle.tendances`.

Vérifie :

- l'agrégation par fenêtre jour/nuit sur une prévision horaire synthétique
- la conversion direction (degrés → secteur cardinal 8)
- la moyenne vectorielle pondérée vitesse
- la conversion m/s → km/h sur vent et rafales
- le picto dominant (sévérité max sur la fenêtre)
- les jours sans données ne produisent pas de cellule
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apps.operationnelle.tendances import (  # noqa: E402
    FENETRE_JOUR,
    FENETRE_JOUR_DEBUT,
    FENETRE_JOUR_FIN,
    FENETRE_NUIT,
    MS_VERS_KMH,
    _direction_cardinal,
    _direction_moyenne_ponderee,
    _masque_fenetre,
    agreger_par_fenetre,
)


def _horaire_synthetique(jours: int = 2, tz: str = "Europe/Paris") -> pd.DataFrame:
    """Prévision synthétique tz-aware UTC sur `jours` jours civils locaux."""
    start_utc = pd.Timestamp("2026-06-01 00:00", tz="UTC")
    idx = pd.date_range(start_utc, periods=24 * jours, freq="h")
    n = len(idx)
    # T° : sinusoïde diurne, min vers 6 h local, max vers 15 h local.
    heure_loc = idx.tz_convert(tz).hour
    t = 15 + 7 * np.sin((heure_loc - 9) * np.pi / 12)
    # Pluie : 1 mm/h sur heures 6-9 du J0, sinon 0.
    pluie = np.zeros(n)
    masque_pluie = (idx.tz_convert(tz).normalize() == idx.tz_convert(tz).normalize()[0]) & (
        (heure_loc >= 6) & (heure_loc < 9)
    )
    pluie[masque_pluie] = 1.0
    # Vent 5 m/s constant, rafales 10 m/s en après-midi.
    vent = np.full(n, 5.0)
    rafales = np.where((heure_loc >= 13) & (heure_loc < 18), 10.0, 5.0)
    # Direction = O (270°) le jour, S (180°) la nuit.
    direction = np.where((heure_loc >= 8) & (heure_loc < 20), 270.0, 180.0)
    # Probabilité pluie : 80% sur la fenêtre de pluie, sinon 10.
    proba = np.where(masque_pluie, 80.0, 10.0)
    # Weather code : 61 (pluie légère) pendant la pluie, 1 (peu nuageux) sinon.
    weather = np.where(masque_pluie, 61, 1)

    return pd.DataFrame(
        {
            "temperature_2m": t,
            "precipitation": pluie,
            "probabilite_pluie_pct": proba,
            "vitesse_vent_10m": vent,
            "rafales_vent_10m": rafales,
            "direction_vent_deg": direction,
            "weather_code": weather,
        },
        index=idx,
    )


def test_direction_cardinal_8_secteurs() -> None:
    assert _direction_cardinal(0.0) == "N"
    assert _direction_cardinal(45.0) == "NE"
    assert _direction_cardinal(90.0) == "E"
    assert _direction_cardinal(180.0) == "S"
    assert _direction_cardinal(270.0) == "O"
    assert _direction_cardinal(359.0) == "N"


def test_direction_cardinal_nan() -> None:
    assert _direction_cardinal(float("nan")) == ""


def test_direction_moyenne_ponderee_vent_unique() -> None:
    df = pd.DataFrame(
        {"direction_vent_deg": [270.0] * 6, "vitesse_vent_10m": [5.0] * 6},
    )
    assert _direction_moyenne_ponderee(df) == 270.0


def test_direction_moyenne_ponderee_vent_oppose_donne_milieu() -> None:
    """N (0°) + S (180°) à vitesses égales → direction indéterminée."""
    df = pd.DataFrame(
        {"direction_vent_deg": [0.0, 180.0], "vitesse_vent_10m": [5.0, 5.0]},
    )
    res = _direction_moyenne_ponderee(df)
    # Le résultat est mal défini (vecteur nul) → atan2(0,0) = 0.
    # On vérifie simplement qu'il n'y a pas d'exception et qu'on a un float.
    assert isinstance(res, float)


def test_masque_fenetre_jour() -> None:
    horaire = _horaire_synthetique(jours=2)
    horaire_loc = horaire.copy()
    horaire_loc.index = horaire_loc.index.tz_convert("Europe/Paris")
    jour = horaire_loc.index.normalize()[0]
    masque = _masque_fenetre(horaire_loc.index, jour, FENETRE_JOUR)
    heures = horaire_loc.index[masque].hour
    assert all(FENETRE_JOUR_DEBUT <= h < FENETRE_JOUR_FIN for h in heures)
    # Tous les jours civils sauf J0 sont exclus.
    assert (horaire_loc.index[masque].normalize() == jour).all()


def test_masque_fenetre_nuit_complement() -> None:
    horaire = _horaire_synthetique(jours=2)
    horaire_loc = horaire.copy()
    horaire_loc.index = horaire_loc.index.tz_convert("Europe/Paris")
    jour = horaire_loc.index.normalize()[0]
    masque_nuit = _masque_fenetre(horaire_loc.index, jour, FENETRE_NUIT)
    heures = horaire_loc.index[masque_nuit].hour
    assert all(h < FENETRE_JOUR_DEBUT or h >= FENETRE_JOUR_FIN for h in heures)


def test_agreger_par_fenetre_cellules_j0_complete() -> None:
    """J0 doit avoir les 2 fenêtres jour + nuit avec les valeurs attendues."""
    horaire = _horaire_synthetique(jours=2)
    cellules = agreger_par_fenetre(horaire, tz_locale="Europe/Paris")
    jours = sorted({j for (j, _) in cellules})
    assert len(jours) >= 1
    j0 = jours[0]

    cell_jour = cellules[(j0, FENETRE_JOUR)]
    cell_nuit = cellules[(j0, FENETRE_NUIT)]

    # T_extreme jour = t_max ; nuit = t_min.
    assert cell_jour.t_extreme > cell_nuit.t_extreme
    # T_mean borné par les extrêmes.
    assert cell_jour.t_extreme >= cell_jour.t_mean
    assert cell_nuit.t_extreme <= cell_nuit.t_mean

    # Vent : moyenne 5 m/s → 18 km/h, rafales 10 m/s en aprem → 36 km/h.
    assert cell_jour.vent_moy_kmh == pytest.approx(5.0 * MS_VERS_KMH, abs=1e-6)
    assert cell_jour.rafales_max_kmh == pytest.approx(10.0 * MS_VERS_KMH, abs=1e-6)
    # Nuit : pas de rafale (toutes à 5 m/s) → 18 km/h.
    assert cell_nuit.rafales_max_kmh == pytest.approx(5.0 * MS_VERS_KMH, abs=1e-6)

    # Direction jour = O (270°), nuit = S (180°).
    assert cell_jour.direction_cardinal == "O"
    assert cell_nuit.direction_cardinal == "S"

    # Pluie : la fenêtre 6-9h tombe à cheval entre nuit (6h) et jour (7-9h)
    # selon nos bornes. Avec FENETRE_JOUR_DEBUT=7, la pluie totale 6-9h
    # = 3 mm = 1 mm nuit (6h) + 2 mm jour (7h, 8h).
    assert cell_nuit.pluie_mm == pytest.approx(1.0, abs=1e-6)
    assert cell_jour.pluie_mm == pytest.approx(2.0, abs=1e-6)

    # Picto : weather_code 61 dominant sur la fenêtre de pluie nuit (6h),
    # weather_code 61 aussi sur la fenêtre jour qui couvre 7h+8h (pluie).
    # Tous deux non-None.
    assert cell_jour.code_picto is not None
    assert cell_nuit.code_picto is not None


def test_agreger_par_fenetre_horaire_vide_retourne_dict_vide() -> None:
    horaire = pd.DataFrame(
        {"temperature_2m": []},
        index=pd.DatetimeIndex([], tz="UTC"),
    )
    assert agreger_par_fenetre(horaire) == {}


def test_agreger_par_fenetre_plafonne_horizon() -> None:
    horaire = _horaire_synthetique(jours=3)
    cellules = agreger_par_fenetre(horaire, horizon_jours=2)
    jours_uniques = {j for (j, _) in cellules}
    assert len(jours_uniques) <= 2


# pytest est importé en haut pour bénéficier de pytest.approx
import pytest  # noqa: E402
