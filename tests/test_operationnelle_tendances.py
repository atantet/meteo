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
    KELVIN_VERS_CELSIUS,
    MIN_HEURES_PAR_FENETRE,
    MS_VERS_KMH,
    _direction_cardinal,
    _direction_moyenne_ponderee,
    _masque_fenetre,
    agreger_par_fenetre,
    proba_max_par_fenetre,
)


def _horaire_synthetique(jours: int = 2, tz: str = "Europe/Paris") -> pd.DataFrame:
    """Prévision synthétique tz-aware UTC sur `jours` jours civils locaux.

    Convention socle : `temperature_2m` est en kelvin (cf.
    `meteo_socle.sources.openmeteo`). On stocke donc en K et les tests
    vérifient que la sortie agrégée est bien en °C.
    """
    start_utc = pd.Timestamp("2026-06-01 00:00", tz="UTC")
    idx = pd.date_range(start_utc, periods=24 * jours, freq="h")
    n = len(idx)
    # T° en °C : sinusoïde diurne, min vers 6 h local, max vers 15 h local.
    # On convertit en K pour respecter la convention socle.
    heure_loc = idx.tz_convert(tz).hour
    t_celsius = 15 + 7 * np.sin((heure_loc - 9) * np.pi / 12)
    t = t_celsius + KELVIN_VERS_CELSIUS
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


def test_masque_fenetre_nuit_contigue() -> None:
    """La nuit J = soirée [19,24) de J-1 + matinée [0,7) de J (contiguë)."""
    horaire = _horaire_synthetique(jours=2)
    horaire_loc = horaire.copy()
    horaire_loc.index = horaire_loc.index.tz_convert("Europe/Paris")
    # On vise la nuit du 2e jour (J1) : sa soirée de veille (J0) est dans
    # les données, donc la nuit doit être complète (soir J0 + matin J1).
    jours = horaire_loc.index.normalize().unique().sort_values()
    j1 = jours[1]
    masque_nuit = _masque_fenetre(horaire_loc.index, j1, FENETRE_NUIT)
    idx_nuit = horaire_loc.index[masque_nuit]
    heures = idx_nuit.hour
    # Toutes les heures sont bien hors de la plage jour.
    assert all(h < FENETRE_JOUR_DEBUT or h >= FENETRE_JOUR_FIN for h in heures)
    # Les heures de soirée (>= 19 h) appartiennent à J-1 (= J0)...
    soir = idx_nuit[idx_nuit.hour >= FENETRE_JOUR_FIN]
    assert (soir.normalize() == jours[0]).all()
    # ...et les heures de matinée (< 7 h) appartiennent à J1.
    matin = idx_nuit[idx_nuit.hour < FENETRE_JOUR_DEBUT]
    assert (matin.normalize() == j1).all()
    # Nuit complète : 5 h de soirée (19-23) + 7 h de matinée (0-6) = 12 h.
    assert len(idx_nuit) == 12


def test_proba_max_par_fenetre_max_des_bins_de_la_fenetre() -> None:
    """Proba MF par bin → max sur la fenêtre 12 h (UTC), bins alignés minuit."""
    from apps.operationnelle.tendances import FENETRE_JOUR, FENETRE_NUIT

    # Bins 6 h : 15/06 00→10, 06→50, 12→80, 18→30 ; 16/06 00→25.
    bins = pd.Series(
        [10.0, 50.0, 80.0, 30.0, 25.0],
        index=pd.DatetimeIndex(
            [
                "2026-06-15 00:00",
                "2026-06-15 06:00",
                "2026-06-15 12:00",
                "2026-06-15 18:00",
                "2026-06-16 00:00",
            ],
            tz="UTC",
        ),
    )
    out = proba_max_par_fenetre(bins, tz_locale="UTC")
    j15 = pd.Timestamp("2026-06-15", tz="UTC")
    j16 = pd.Timestamp("2026-06-16", tz="UTC")
    # Jour [06,18) du 15 = max(50, 80) = 80.
    assert out[(j15, FENETRE_JOUR)] == 80.0
    # Nuit du 15 = matinée [0,6) du 15 → bin 00 = 10.
    assert out[(j15, FENETRE_NUIT)] == 10.0
    # Nuit du 16 = soirée [18,24) du 15 (bin 18→30) + matinée [0,6) du 16
    # (bin 00→25) → max = 30 (vérifie l'assignation soirée → nuit du lendemain).
    assert out[(j16, FENETRE_NUIT)] == 30.0


def test_proba_max_par_fenetre_vide_si_bins_absents() -> None:
    assert proba_max_par_fenetre(None) == {}
    assert proba_max_par_fenetre(pd.Series(dtype="float64")) == {}


def test_agreger_par_fenetre_proba_injectee_pas_du_df() -> None:
    """La proba vient du dict ``proba_par_fenetre``, jamais d'une colonne du df."""
    from apps.operationnelle.tendances import FENETRE_JOUR

    horaire = _horaire_synthetique(jours=2)
    # Même avec une colonne proba dans le df, elle est ignorée (champ non modèle).
    horaire = horaire.copy()
    horaire["probabilite_pluie_pct"] = 99.0
    jour0 = pd.DatetimeIndex(horaire.index).tz_convert("UTC").normalize()[0]
    proba = {(jour0, FENETRE_JOUR): 42.0}
    cellules = agreger_par_fenetre(horaire, tz_locale="UTC", proba_par_fenetre=proba)
    assert cellules[(jour0, FENETRE_JOUR)].prob_pluie_pct == 42.0
    # Une fenêtre sans entrée proba → NaN (pas 99 du df).
    import math

    autres = [c for (k, c) in cellules.items() if k != (jour0, FENETRE_JOUR)]
    assert any(math.isnan(c.prob_pluie_pct) for c in autres)


def test_agreger_par_fenetre_cellules_valeurs() -> None:
    """Un jour complet a jour + nuit aux valeurs attendues ; nuit incomplète écartée."""
    horaire = _horaire_synthetique(jours=2)
    cellules = agreger_par_fenetre(horaire, tz_locale="Europe/Paris")
    jours = sorted({j for (j, _) in cellules})
    assert len(jours) >= 1
    j0 = jours[0]

    cell_jour = cellules[(j0, FENETRE_JOUR)]
    # La nuit de J0 est INCOMPLÈTE (soirée de la veille hors prévision) → écartée
    # par le garde-fou « jamais de fausse valeur » (cumul/extrême non fiable).
    assert (j0, FENETRE_NUIT) not in cellules
    # Première nuit complète (soirée + matinée) pour la comparaison jour/nuit.
    nuits = sorted(j for (j, f) in cellules if f == FENETRE_NUIT)
    cell_nuit = cellules[(nuits[0], FENETRE_NUIT)]

    # T_extreme jour = t_max ; nuit = t_min.
    assert cell_jour.t_extreme > cell_nuit.t_extreme
    # T_mean borné par les extrêmes.
    assert cell_jour.t_extreme >= cell_jour.t_mean
    assert cell_nuit.t_extreme <= cell_nuit.t_mean
    # T° en °C en sortie (entrée en K) : sinusoïde 15 ± 7 °C → toutes les
    # valeurs sont dans [-20, 50] °C. Si la conversion K→°C est oubliée,
    # on aurait des valeurs ~288 K → ce test fait fail.
    for c in (cell_jour, cell_nuit):
        assert -20.0 < c.t_mean < 50.0, f"t_mean hors plage °C : {c.t_mean}"
        assert -20.0 < c.t_extreme < 50.0, f"t_extreme hors plage °C : {c.t_extreme}"

    # Vent : moyenne 5 m/s → 18 km/h, rafales 10 m/s en aprem → 36 km/h.
    assert cell_jour.vent_moy_kmh == pytest.approx(5.0 * MS_VERS_KMH, abs=1e-6)
    assert cell_jour.rafales_max_kmh == pytest.approx(10.0 * MS_VERS_KMH, abs=1e-6)
    # Nuit complète : la rafale de 10 m/s (13-17 h) tombe en « jour » → nuit à 18 km/h.
    assert cell_nuit.rafales_max_kmh == pytest.approx(5.0 * MS_VERS_KMH, abs=1e-6)

    # Direction jour = O (270°) ; la nuit garde une direction définie (non vide).
    assert cell_jour.direction_cardinal == "O"
    assert cell_nuit.direction_cardinal != ""

    # Pluie : 1 mm/h aux heures 6, 7, 8 du J0 → 3 mm en jour J0.
    assert cell_jour.pluie_mm == pytest.approx(3.0, abs=1e-6)
    # Plus de pictogramme dans l'App 2 (ADR-0014 D2).
    assert not hasattr(cell_jour, "code_picto")


def test_cellule_weather_code_dominant_si_colonne_presente() -> None:
    """Picto semaine unifié (ADR-0021) : weather_code dominant si le df le porte."""
    from apps.operationnelle.tendances import _agreger_cellule

    idx = pd.date_range("2026-06-15 06:00", periods=4, freq="h", tz="Europe/Paris")
    group = pd.DataFrame(
        {
            "temperature_2m": [290.0] * 4,
            "cloud_cover": [0.9] * 4,
            "precipitation": [0.0, 1.0, 2.0, 0.0],
            "weather_code": pd.array([3, 61, 95, 3], dtype="Int64"),  # orage = sévérité max
        },
        index=idx,
    )
    cell = _agreger_cellule(group, FENETRE_JOUR)
    assert cell.weather_code == 95  # code dominant (orage) sur la fenêtre

    # Sans colonne weather_code → None (rendu nébulosité+pluie historique).
    cell_sans = _agreger_cellule(group.drop(columns=["weather_code"]), FENETRE_JOUR)
    assert cell_sans.weather_code is None


def test_agreger_par_fenetre_convertit_k_vers_celsius_exactement() -> None:
    """Entrée 288.15 K constante → sortie 15.00 °C exact (delta < 1e-6)."""
    idx = pd.date_range("2026-06-01 00:00", periods=24, freq="h", tz="UTC")
    horaire = pd.DataFrame(
        {
            "temperature_2m": [288.15] * 24,
            "precipitation": [0.0] * 24,
            "probabilite_pluie_pct": [0.0] * 24,
            "vitesse_vent_10m": [0.0] * 24,
            "rafales_vent_10m": [0.0] * 24,
            "direction_vent_deg": [180.0] * 24,
            "weather_code": [0] * 24,
        },
        index=idx,
    )
    cellules = agreger_par_fenetre(horaire, tz_locale="Europe/Paris")
    for cell in cellules.values():
        assert cell.t_mean == pytest.approx(15.0, abs=1e-6)
        assert cell.t_extreme == pytest.approx(15.0, abs=1e-6)


def test_agreger_par_fenetre_etp_cumul() -> None:
    """ETP socle (mm/h) × 0.1 : cumul jour 1.2 mm (12 h) et nuit selon couverture.

    Bins UTC (ADR-0011 D5). Nuit contiguë : nuit J = soirée [18,24) de J-1
    (6 h) + matinée [0,6) de J (6 h). La nuit du 1ᵉʳ jour n'a pas de soirée de
    veille (données commencent à 00 h) → 6 h seulement → 0.6 mm. La nuit du
    2ᵉ jour est complète (6 h + 6 h = 12 h) → 1.2 mm.
    """
    horaire = _horaire_synthetique(jours=2)
    etp = pd.Series(
        [0.1] * 48,
        index=pd.date_range("2026-06-01 00:00", periods=48, freq="h", tz="UTC"),
    )
    cellules = agreger_par_fenetre(horaire, tz_locale="UTC", etp_horaire=etp)
    jours = sorted({j for (j, _) in cellules})
    j0, j1 = jours[0], jours[1]
    # Fenêtre jour J0 = 12 heures × 0.1 mm/h = 1.2 mm
    assert cellules[(j0, FENETRE_JOUR)].etp_mm == pytest.approx(1.2, abs=1e-6)
    # Nuit J0 INCOMPLÈTE (matinée seule, soirée de la veille hors prévision) →
    # ÉCARTÉE : on ne montre pas un cumul sous-estimé (« jamais de fausse valeur »).
    assert (j0, FENETRE_NUIT) not in cellules
    # Nuit J1 COMPLÈTE = soirée J0 (6 h) + matinée J1 (6 h) = 12 h = 1.2 mm
    assert cellules[(j1, FENETRE_NUIT)].etp_mm == pytest.approx(1.2, abs=1e-6)


def test_agreger_par_fenetre_run_tronque_ecarte_jour_incomplet() -> None:
    """Run partiellement publié (tronqué le matin) → la journée incomplète n'est
    PAS rendue : jamais de faux max (cas réel du 16/06 où l'après-midi manquait)."""
    # Données du 01/06 00:00 au 02/06 09:00 UTC : le 02/06 s'arrête à 09 h →
    # l'après-midi (le pic de T°) manque pour la fenêtre jour du 02/06.
    idx = pd.date_range("2026-06-01 00:00", "2026-06-02 09:00", freq="h", tz="UTC")
    n = len(idx)
    # T° qui culminerait l'après-midi : si la fenêtre tronquée était rendue, son
    # « max » serait celui du matin (faux). On veut qu'elle soit écartée.
    heure = idx.hour
    t = 288.15 + 8.0 * np.sin((heure - 9) * np.pi / 12)
    horaire = pd.DataFrame(
        {
            "temperature_2m": t,
            "precipitation": [0.0] * n,
            "vitesse_vent_10m": [3.0] * n,
            "rafales_vent_10m": [5.0] * n,
            "direction_vent_deg": [200.0] * n,
            "weather_code": [1] * n,
        },
        index=idx,
    )
    cellules = agreger_par_fenetre(horaire, tz_locale="UTC")
    j02 = pd.Timestamp("2026-06-02", tz="UTC")
    # Le jour 02/06 est tronqué (données jusqu'à 09 h) → AUCUNE cellule jour.
    assert (j02, FENETRE_JOUR) not in cellules
    # Le jour 01/06 (complet) est bien présent.
    assert (pd.Timestamp("2026-06-01", tz="UTC"), FENETRE_JOUR) in cellules


def test_agreger_par_fenetre_sans_etp_donne_nan() -> None:
    """Sans série ETP, l'ETP de chaque cellule est NaN."""
    horaire = _horaire_synthetique(jours=1)
    cellules = agreger_par_fenetre(horaire, tz_locale="UTC")
    for cell in cellules.values():
        assert np.isnan(cell.etp_mm)


def test_agreger_par_fenetre_filtre_fenetres_trop_courtes() -> None:
    """Une fenêtre couvrant < MIN_HEURES_PAR_FENETRE est écartée."""
    # Crée une prévision ne couvrant que MIN-1 heures sur la fenêtre jour
    # du 01/06 (heures 7h-9h locales soit 3 heures si MIN=4).
    n_couvert = MIN_HEURES_PAR_FENETRE - 1
    debut = pd.Timestamp(f"2026-06-01 0{FENETRE_JOUR_DEBUT}:00", tz="UTC")
    idx = pd.date_range(debut, periods=n_couvert, freq="h")
    horaire = pd.DataFrame(
        {
            "temperature_2m": [288.15] * n_couvert,
            "precipitation": [0.0] * n_couvert,
            "probabilite_pluie_pct": [0.0] * n_couvert,
            "vitesse_vent_10m": [1.0] * n_couvert,
            "rafales_vent_10m": [1.0] * n_couvert,
            "direction_vent_deg": [180.0] * n_couvert,
            "weather_code": [0] * n_couvert,
        },
        index=idx,
    )
    cellules = agreger_par_fenetre(horaire, tz_locale="UTC")
    # Aucune cellule créée car < MIN heures couvertes sur la fenêtre jour.
    assert (pd.Timestamp("2026-06-01"), FENETRE_JOUR) not in cellules


def test_agreger_par_fenetre_robuste_au_concat_heterogene() -> None:
    """Reproduit le scénario du toggle « 48 h passées » côté tendance.

    `pd.concat([ERA5, forecast])` peut produire un DataFrame dont
    certaines colonnes sont en dtype `object` (NaN ajoutés par pandas
    pour les colonnes présentes seulement d'un côté). `np.deg2rad`,
    `np.exp` etc. dans les calculs de tendance plantent alors avec
    « loop of ufunc does not support argument 0 of type ... ».
    `agreger_par_fenetre` doit caster en float toutes les colonnes
    numériques en interne, avant tout calcul.
    """
    idx = pd.date_range("2026-06-01 00:00", periods=24, freq="h", tz="UTC")
    # Forçage du dtype object après création (Series avec index personnalisé
    # passées au constructeur reindexent et nullifient les valeurs).
    df_object = pd.DataFrame(
        {
            "temperature_2m": [288.15] * 24,
            "precipitation": [0.0] * 24,
            "probabilite_pluie_pct": [0.0] * 24,
            "vitesse_vent_10m": [2.0] * 24,
            "rafales_vent_10m": [3.0] * 24,
            "direction_vent_deg": [180.0] * 24,
            "weather_code": [0] * 24,
        },
        index=idx,
    )
    for col in df_object.columns:
        if col != "weather_code":
            df_object[col] = df_object[col].astype("object")
    cellules = agreger_par_fenetre(df_object, tz_locale="UTC")
    # Ne doit pas planter ; au moins une cellule jour produite avec
    # des valeurs numériques cohérentes.
    assert cellules
    cell_jour = next(c for (_, f), c in cellules.items() if f == FENETRE_JOUR)
    assert cell_jour.t_mean == pytest.approx(15.0, abs=1e-6)
    assert cell_jour.direction_cardinal == "S"


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
