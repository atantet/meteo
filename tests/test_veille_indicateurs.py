"""Tests `apps.veille.indicateurs` — calculs sur prévision synthétique."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


CONFIG_TEST = {
    # Site = Pleine-Fougères (cf. ADR-0001 règle 3) — utile pour calcul_etp.
    "site": {"latitude": 48.5420, "longitude": -1.6155, "altitude": 30},
    "indicateurs": {},
}


def _prevision_synthetique(
    duree_h: int = 72,
    t_celsius: float = 15.0,
    pluie_horaire_mm: float = 0.0,
    vent_ms: float = 5.0,
    rafales_ms: float = 9.0,
    humidite: float = 0.7,
    rayonnement_jh: float = 0.0,
    proba_pluie_pct: float = 0.0,
    direction_deg: float = 270.0,  # vent d'ouest par défaut
) -> pd.DataFrame:
    """Construit une prévision horaire homogène pour tests."""
    index = pd.date_range("2024-06-15 00:00:00+00:00", periods=duree_h, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(duree_h, t_celsius + 273.15),
            "humidite_relative": np.full(duree_h, humidite),
            "vitesse_vent_10m": np.full(duree_h, vent_ms),
            "rafales_vent_10m": np.full(duree_h, rafales_ms),
            "direction_vent_deg": np.full(duree_h, direction_deg),
            "rayonnement_global": np.full(duree_h, rayonnement_jh),
            "precipitation": np.full(duree_h, pluie_horaire_mm),
            "probabilite_pluie_pct": np.full(duree_h, proba_pluie_pct),
        },
        index=index,
    )


def _patch_etp(etp_horaire_mm: float):
    """Helper : mock `apps.veille.indicateurs.calcul_etp` pour valeur constante."""

    def fake_calcul_etp(df, lat, lon, alt):
        return pd.Series(etp_horaire_mm, index=df.index)

    return patch("apps.veille.indicateurs.calcul_etp", side_effect=fake_calcul_etp)


def test_calculer_indicateurs_basique() -> None:
    """ETP mockée à 0.1 mm/h constante — vérifie les sommes et conversions."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with _patch_etp(0.1):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)

    assert ind.temperature_min_24h_celsius == pytest.approx(15.0)
    assert ind.temperature_max_24h_celsius == pytest.approx(15.0)
    assert ind.cumul_pluie_24h_mm == pytest.approx(0.0)
    assert ind.vent_max_24h_kmh == pytest.approx(18.0)  # 5 m/s × 3.6
    assert ind.rafales_max_24h_kmh == pytest.approx(32.4)  # 9 m/s × 3.6
    # ETP mockée : 0.1 mm/h × 24 = 2.4 mm/j.
    assert ind.etp_jour_mm == pytest.approx(2.4)
    # Série ETP horaire 48 h : 48 valeurs à 0.1 mm/h.
    assert len(ind.etp_horaire_48h) == 48
    assert ind.etp_horaire_48h.sum() == pytest.approx(4.8)
    # Probabilité par défaut : 0 % partout.
    assert ind.prob_pluie_max_24h_pct == pytest.approx(0.0)
    assert ind.prob_pluie_max_48h_pct == pytest.approx(0.0)


def test_calculer_indicateurs_proba_pluie() -> None:
    """Probabilité de pluie variable → max calculé correctement par fenêtre."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    # 0-24h : max à 30% ; 24-48h : max à 60%.
    prevision.loc[prevision.index[:24], "probabilite_pluie_pct"] = 30.0
    prevision.loc[prevision.index[24:48], "probabilite_pluie_pct"] = 60.0
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with _patch_etp(0.1):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.prob_pluie_max_24h_pct == pytest.approx(30.0)
    assert ind.prob_pluie_max_48h_pct == pytest.approx(60.0)


def test_calculer_indicateurs_direction_dominante() -> None:
    """Direction constante (270°) → cardinal O ; T+0 = 1ère heure ≥ now."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(direction_deg=270.0)
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with _patch_etp(0.1):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.direction_vent_dominante_cardinal == "O"
    assert ind.direction_vent_dominante_deg == pytest.approx(270.0)
    assert ind.prevision_t0_utc == now


def test_degrees_to_cardinal() -> None:
    from apps.veille.indicateurs import degrees_to_cardinal

    assert degrees_to_cardinal(0) == "N"
    assert degrees_to_cardinal(90) == "E"
    assert degrees_to_cardinal(180) == "S"
    assert degrees_to_cardinal(270) == "O"
    assert degrees_to_cardinal(45) == "NE"
    assert degrees_to_cardinal(315) == "NO"
    # Wrap-around.
    assert degrees_to_cardinal(360) == "N"


def test_calculer_indicateurs_proba_pluie_colonne_absente() -> None:
    """Si la colonne probabilite_pluie_pct est absente → 0 par défaut."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique().drop(columns=["probabilite_pluie_pct"])
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with _patch_etp(0.1):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.prob_pluie_max_24h_pct == 0.0


def test_calculer_indicateurs_alerte_gel_canicule() -> None:
    """Variation T° sur 24 h → min (gel) et max (canicule) distincts."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    t_pattern = [-3.0] * 8 + [20.0] * 8 + [-1.0] * 8
    prevision.loc[prevision.index[:24], "temperature_2m"] = np.array(t_pattern) + 273.15
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with _patch_etp(0.1):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.temperature_min_24h_celsius == pytest.approx(-3.0)
    assert ind.temperature_max_24h_celsius == pytest.approx(20.0)


def test_calculer_indicateurs_cumuls_pluie() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(pluie_horaire_mm=1.0)
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with _patch_etp(0.0):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.cumul_pluie_24h_mm == pytest.approx(24.0)
    assert ind.cumul_pluie_48h_mm == pytest.approx(48.0)


def test_calculer_indicateurs_min_nuit_prochaine_cible_j1_0_6h() -> None:
    """Le min nuit à venir ne regarde que J+1 [0, 6 h) local, pas tout le 24/48 h."""
    from apps.veille.indicateurs import calculer_indicateurs

    # 72 h depuis 2024-06-15 00:00 UTC. tz Europe/Paris (été, UTC+2).
    prevision = _prevision_synthetique(duree_h=72, t_celsius=15.0)
    now = pd.Timestamp("2024-06-15 09:00", tz="Europe/Paris").tz_convert("UTC")
    idx_local = prevision.index.tz_convert("Europe/Paris")
    # J+1 [0,6 h) locale = nuit à venir → 11 °C.
    masque = (
        (idx_local.normalize() == pd.Timestamp("2024-06-16", tz="Europe/Paris"))
        & (idx_local.hour >= 0)
        & (idx_local.hour < 6)
    )
    prevision.loc[masque, "temperature_2m"] = 11.0 + 273.15
    # Heure très froide HORS nuit J+1 (après-midi J0) : ne doit PAS compter.
    idx_pm = (idx_local.normalize() == pd.Timestamp("2024-06-15", tz="Europe/Paris")) & (
        idx_local.hour == 15
    )
    prevision.loc[idx_pm, "temperature_2m"] = -5.0 + 273.15
    with _patch_etp(0.1):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.temperature_min_nuit_prochaine_celsius == pytest.approx(11.0)


def test_calculer_indicateurs_fenetre_ancree_minuit_local() -> None:
    """La fenêtre démarre à minuit local du jour de now (heures avant ignorées)."""
    from apps.veille.indicateurs import calculer_indicateurs

    # 72 h depuis le 2024-06-15 00:00 UTC. now = matin du 16 (comme l'envoi
    # réel) ; minuit local du 16 (Europe/Paris été) = 2024-06-15 22:00 UTC.
    prevision = _prevision_synthetique(duree_h=72, t_celsius=15.0)
    now = pd.Timestamp("2024-06-16 09:00", tz="Europe/Paris").tz_convert("UTC")
    debut_utc = now.tz_convert("Europe/Paris").normalize().tz_convert("UTC")
    # Tout ce qui précède minuit local du 16 est très froid → doit être exclu.
    prevision.loc[prevision.index < debut_utc, "temperature_2m"] = -10.0 + 273.15
    with _patch_etp(0.1):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.temperature_min_24h_celsius == pytest.approx(15.0)
    # t0 = minuit local, pas l'heure d'envoi.
    assert ind.prevision_t0_utc == debut_utc


def test_ancre_fenetre_matin_minuit_apres_midi_midi() -> None:
    """L'ancre = 00 h local le matin (< 12 h), 12 h local l'après-midi."""
    from apps.veille.indicateurs import ancre_fenetre

    tz = "Europe/Paris"
    # Matin (06:30 local) → ancre 00 h locale du même jour.
    matin = pd.Timestamp("2024-06-16 06:30", tz=tz).tz_convert("UTC")
    assert ancre_fenetre(matin, tz) == pd.Timestamp("2024-06-16 00:00", tz=tz).tz_convert("UTC")
    # Après-midi (18:30 local) → ancre 12 h locale du même jour.
    apres_midi = pd.Timestamp("2024-06-16 18:30", tz=tz).tz_convert("UTC")
    assert ancre_fenetre(apres_midi, tz) == pd.Timestamp("2024-06-16 12:00", tz=tz).tz_convert(
        "UTC"
    )
    # Pile à midi local = après-midi (≥ 12 h).
    midi = pd.Timestamp("2024-06-16 12:00", tz=tz).tz_convert("UTC")
    assert ancre_fenetre(midi, tz) == midi


def test_moment_envoi_matin_apres_midi() -> None:
    """moment_envoi déduit matin/après-midi de l'heure locale."""
    from apps.veille.indicateurs import moment_envoi

    tz = "Europe/Paris"
    assert moment_envoi(pd.Timestamp("2024-06-16 06:30", tz=tz).tz_convert("UTC"), tz) == "matin"
    assert (
        moment_envoi(pd.Timestamp("2024-06-16 18:30", tz=tz).tz_convert("UTC"), tz) == "après-midi"
    )
    # 11 h 59 = encore matin ; 12 h = après-midi.
    assert moment_envoi(pd.Timestamp("2024-06-16 11:59", tz=tz).tz_convert("UTC"), tz) == "matin"
    assert (
        moment_envoi(pd.Timestamp("2024-06-16 12:00", tz=tz).tz_convert("UTC"), tz) == "après-midi"
    )


def test_calculer_indicateurs_fenetre_ancree_midi_apres_midi() -> None:
    """Envoi de l'après-midi : la fenêtre démarre à 12 h local (matin exclu)."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(duree_h=72, t_celsius=15.0)
    # Envoi à 16 h local le 16 → ancre = 12 h locale du 16.
    now = pd.Timestamp("2024-06-16 16:00", tz="Europe/Paris").tz_convert("UTC")
    debut_utc = pd.Timestamp("2024-06-16 12:00", tz="Europe/Paris").tz_convert("UTC")
    # Tout ce qui précède 12 h locale du 16 (dont la nuit/matin déjà passés)
    # est très froid → doit être exclu de la fenêtre.
    prevision.loc[prevision.index < debut_utc, "temperature_2m"] = -10.0 + 273.15
    with _patch_etp(0.1):
        ind = calculer_indicateurs(prevision, now, CONFIG_TEST)
    assert ind.temperature_min_48h_celsius == pytest.approx(15.0)
    # t0 = 12 h locale (ancre après-midi), pas minuit ni l'heure d'envoi.
    assert ind.prevision_t0_utc == debut_utc


def test_calculer_indicateurs_vide_raise() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(duree_h=24)
    now = pd.Timestamp("2024-06-30 00:00:00+00:00")
    with pytest.raises(ValueError):
        calculer_indicateurs(prevision, now, CONFIG_TEST)


def test_calculer_indicateurs_etp_socle_appelee() -> None:
    """Smoke test : calcul_etp est appelée avec les bons inputs site."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with patch("apps.veille.indicateurs.calcul_etp") as mock_etp:
        mock_etp.return_value = pd.Series(0.0, index=prevision.head(48).index)
        calculer_indicateurs(prevision, now, CONFIG_TEST)
    # 2 appels (h24 et h48), avec les coords site Pleine-Fougères.
    assert mock_etp.call_count == 2
    for call in mock_etp.call_args_list:
        args = call.args
        assert args[1] == pytest.approx(48.5420)  # latitude
        assert args[2] == pytest.approx(-1.6155)  # longitude
        assert args[3] == pytest.approx(30)  # altitude
