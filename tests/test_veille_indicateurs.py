"""Tests `apps.veille.indicateurs` — prévi officielle MF, heure locale (ADR-0014).

Fixtures en unités natives socle (K, m/s, mm, fraction) ; assertions de plage sur
la sortie affichée. Plus d'ETP (retirée de la Veille), plus d'ancrage run :
découpage sur périodes de 6 h locales (``periodes_pleines``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# tz="UTC" → l'heure « locale » coïncide avec l'UTC : les périodes 6 h
# s'alignent sur l'index, ce qui rend les fenêtres prévisibles dans les tests.
CONFIG_UTC = {"site": {"latitude": 48.543648, "longitude": -1.611515, "altitude": 30, "tz": "UTC"}}
CONFIG_PARIS = {
    "site": {"latitude": 48.543648, "longitude": -1.611515, "altitude": 30, "tz": "Europe/Paris"}
}


def _prevision_synthetique(
    duree_h: int = 72,
    debut: str = "2024-06-15 00:00:00+00:00",
    t_celsius: float = 15.0,
    pluie_horaire_mm: float = 0.0,
    vent_ms: float = 5.0,
    rafales_ms: float = 9.0,
    humidite: float = 0.7,
    proba_pluie_pct: float = 0.0,
    direction_deg: float = 270.0,  # vent d'ouest par défaut
) -> pd.DataFrame:
    """Prévision horaire homogène (colonnes socle, comme la source MF)."""
    index = pd.date_range(debut, periods=duree_h, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(duree_h, t_celsius + 273.15),
            "humidite_relative": np.full(duree_h, humidite),
            "vitesse_vent_10m": np.full(duree_h, vent_ms),
            "rafales_vent_10m": np.full(duree_h, rafales_ms),
            "direction_vent_deg": np.full(duree_h, direction_deg),
            "precipitation": np.full(duree_h, pluie_horaire_mm),
            "probabilite_pluie_pct": np.full(duree_h, proba_pluie_pct),
            "weather_code": pd.array([2] * duree_h, dtype="Int64"),
        },
        index=index,
    )


def test_calculer_indicateurs_basique() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_UTC)

    assert ind.temperature_min_24h_celsius == pytest.approx(15.0)
    assert ind.temperature_max_24h_celsius == pytest.approx(15.0)
    assert ind.cumul_pluie_24h_mm == pytest.approx(0.0)
    assert ind.vent_max_24h_kmh == pytest.approx(18.0)  # 5 m/s × 3.6
    assert ind.rafales_max_24h_kmh == pytest.approx(32.4)  # 9 m/s × 3.6
    assert ind.prob_pluie_max_24h_pct == pytest.approx(0.0)
    assert ind.prob_pluie_max_48h_pct == pytest.approx(0.0)
    # Plus de champ ETP dans le bundle.
    assert not hasattr(ind, "etp_jour_mm")


def test_calculer_indicateurs_proba_pluie() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    # tz=UTC + données dès 00:00 → fenêtre dès l'index 0.
    prevision.loc[prevision.index[:24], "probabilite_pluie_pct"] = 30.0
    prevision.loc[prevision.index[24:48], "probabilite_pluie_pct"] = 60.0
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_UTC)
    assert ind.prob_pluie_max_24h_pct == pytest.approx(30.0)
    assert ind.prob_pluie_max_48h_pct == pytest.approx(60.0)


def test_calculer_indicateurs_direction_dominante() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(direction_deg=270.0)
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_UTC)
    assert ind.direction_vent_dominante_cardinal == "O"
    assert ind.direction_vent_dominante_deg == pytest.approx(270.0)
    # 1ʳᵉ période 6 h pleine = Nuit 00:00 (tz=UTC, données dès 00:00).
    assert ind.prevision_t0_local == pd.Timestamp("2024-06-15 00:00", tz="UTC")


def test_degrees_to_cardinal() -> None:
    from apps.veille.indicateurs import degrees_to_cardinal

    assert degrees_to_cardinal(0) == "N"
    assert degrees_to_cardinal(90) == "E"
    assert degrees_to_cardinal(180) == "S"
    assert degrees_to_cardinal(270) == "O"
    assert degrees_to_cardinal(45) == "NE"
    assert degrees_to_cardinal(315) == "NO"
    assert degrees_to_cardinal(360) == "N"


def test_calculer_indicateurs_proba_pluie_colonne_absente() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique().drop(columns=["probabilite_pluie_pct"])
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_UTC)
    assert ind.prob_pluie_max_24h_pct == 0.0


def test_calculer_indicateurs_alerte_gel_canicule() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique()
    t_pattern = [-3.0] * 8 + [20.0] * 8 + [-1.0] * 8
    prevision.loc[prevision.index[:24], "temperature_2m"] = np.array(t_pattern) + 273.15
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_UTC)
    assert ind.temperature_min_24h_celsius == pytest.approx(-3.0)
    assert ind.temperature_max_24h_celsius == pytest.approx(20.0)


def test_calculer_indicateurs_cumuls_pluie() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(pluie_horaire_mm=1.0)
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    ind = calculer_indicateurs(prevision, now, CONFIG_UTC)
    assert ind.cumul_pluie_24h_mm == pytest.approx(24.0)
    assert ind.cumul_pluie_48h_mm == pytest.approx(48.0)


def test_calculer_indicateurs_min_nuit_prochaine_cible_j1_0_6h() -> None:
    """Min de la nuit locale À VENIR (J+1 [0, 6 h) Paris), pas tout le 24/48 h."""
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(duree_h=72, t_celsius=15.0)
    now = pd.Timestamp("2024-06-15 09:00", tz="Europe/Paris").tz_convert("UTC")
    idx_local = prevision.index.tz_convert("Europe/Paris")
    masque = (
        (idx_local.normalize() == pd.Timestamp("2024-06-16", tz="Europe/Paris"))
        & (idx_local.hour >= 0)
        & (idx_local.hour < 6)
    )
    prevision.loc[masque, "temperature_2m"] = 11.0 + 273.15
    # Heure très froide HORS nuit J+1 (après-midi J0) → ne doit PAS compter.
    idx_pm = (idx_local.normalize() == pd.Timestamp("2024-06-15", tz="Europe/Paris")) & (
        idx_local.hour == 15
    )
    prevision.loc[idx_pm, "temperature_2m"] = -5.0 + 273.15
    ind = calculer_indicateurs(prevision, now, CONFIG_PARIS)
    assert ind.temperature_min_nuit_prochaine_celsius == pytest.approx(11.0)


def test_premiere_periode_pleine_exclut_la_queue_passee() -> None:
    """Données dès 05:00 (queue) → 1ʳᵉ période pleine = Matin 06:00 (Nuit exclue)."""
    from apps.veille.indicateurs import calculer_indicateurs

    # Démarre à 05:00 UTC (queue d'une heure) sur 48 h, tz=UTC.
    prevision = _prevision_synthetique(duree_h=48, debut="2024-06-15 05:00:00+00:00")
    now = pd.Timestamp("2024-06-15 06:30", tz="UTC")
    ind = calculer_indicateurs(prevision, now, CONFIG_UTC)
    # Nuit [0,6) partielle (seul 05:00 présent) → exclue ; 1ʳᵉ pleine = Matin 06:00.
    assert ind.prevision_t0_local == pd.Timestamp("2024-06-15 06:00", tz="UTC")


def test_moment_envoi_heure_locale() -> None:
    from apps.veille.indicateurs import moment_envoi

    # 6 h 30 locale (Paris été = 04:30 UTC) → matin.
    assert moment_envoi(pd.Timestamp("2024-06-16 04:30", tz="UTC"), "Europe/Paris") == "matin"
    # 18 h 30 locale (= 16:30 UTC) → après-midi.
    assert moment_envoi(pd.Timestamp("2024-06-16 16:30", tz="UTC"), "Europe/Paris") == "après-midi"


def test_periodes_pleines_et_portion_horaire() -> None:
    from apps.veille.indicateurs import periodes_pleines, portion_horaire

    # Horaire 0-30 h puis pas de 3 h → la portion horaire s'arrête à la rupture.
    idx_1h = pd.date_range("2024-06-15 05:00", periods=20, freq="h", tz="Europe/Paris")
    idx_3h = pd.date_range(
        idx_1h[-1] + pd.Timedelta(hours=3), periods=4, freq="3h", tz="Europe/Paris"
    )
    df = pd.DataFrame({"x": 1.0}, index=idx_1h.append(idx_3h))
    horaire = portion_horaire(df)
    assert horaire.index.max() == idx_1h[-1]  # rupture détectée
    labels = [lab for lab, _, _ in periodes_pleines(horaire)]
    # 05:00→00:00 J+1 : Nuit partielle exclue ; Matin/Après-midi/Soir pleines.
    assert labels[0] == "Matin"
    assert "Nuit" not in labels[:1]


def test_calculer_indicateurs_aucune_periode_pleine_raise() -> None:
    from apps.veille.indicateurs import calculer_indicateurs

    # 3 heures seulement → aucune période de 6 h pleine.
    prevision = _prevision_synthetique(duree_h=3)
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    with pytest.raises(ValueError):
        calculer_indicateurs(prevision, now, CONFIG_UTC)
