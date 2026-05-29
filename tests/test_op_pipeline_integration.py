"""Tests d'intégration offline du pipeline App 2 Op.

Idée : exercer ``calculer_indicateurs_quotidiens`` avec une prévision
synthétique mais réaliste (même colonnes que ``OpenMeteoForecast``),
config complète, et vérifier que toutes les colonnes attendues sont
présentes. Aurait attrapé le bug LWD du 2026-05-29 (column
``heures_humectation`` absente sur Streamlit Cloud Python 3.14).

Pas de network, pas de Streamlit runtime — juste la chaîne de
calcul socle + apps.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _prevision_realiste_open_meteo(n_jours: int = 7) -> pd.DataFrame:
    """Reproduit la signature de ``OpenMeteoForecast.obtenir_prevision``.

    Toutes les colonnes du socle (même celles optionnelles) avec des
    valeurs plausibles pour le climat breton début juin.
    """
    n_h = 24 * n_jours
    idx = pd.date_range("2026-06-01 00:00", periods=n_h, freq="h", tz="UTC")
    # T° cycle diurne 8-18 °C avec amplitude ~10.
    t = 13.0 + 5.0 * np.sin(np.linspace(0, 2 * np.pi * n_jours, n_h))
    # HR inversement corrélée à T° + bruit léger.
    hr = np.clip(0.55 + 0.30 * np.cos(np.linspace(0, 2 * np.pi * n_jours, n_h)), 0.4, 0.95)
    return pd.DataFrame(
        {
            "temperature_2m": t + 273.15,
            "humidite_relative": hr,
            "precipitation": np.full(n_h, 0.2),
            "probabilite_pluie_pct": np.full(n_h, 40.0),
            "vitesse_vent_10m": np.full(n_h, 4.0),
            "rafales_vent_10m": np.full(n_h, 8.0),
            "direction_vent_deg": np.full(n_h, 230.0),
            "rayonnement_global": np.maximum(
                0, 500 * np.sin(np.linspace(0, 2 * np.pi * n_jours, n_h))
            ),
            "etp_open_meteo": np.full(n_h, 0.15),
            "cloud_cover": np.full(n_h, 0.5),
        },
        index=idx,
    )


def _config_reelle() -> dict:
    """Charge la config Op de production (config/operationnelle.yaml)."""
    with open(REPO_ROOT / "config" / "operationnelle.yaml") as f:
        return yaml.safe_load(f)


def test_pipeline_complete_produit_toutes_colonnes_attendues() -> None:
    """Pipeline `calculer_indicateurs_quotidiens` produit toutes les colonnes.

    En particulier ``mildiou_heures_humectation`` doit exister quand la
    config mildiou_smith est active (cas qui a manqué sur Streamlit
    Cloud 2026-05-29).
    """
    from apps.operationnelle.indicateurs import calculer_indicateurs_quotidiens

    prev = _prevision_realiste_open_meteo(n_jours=7)
    config = _config_reelle()
    now = pd.Timestamp("2026-06-01 00:00", tz="UTC")
    quot = calculer_indicateurs_quotidiens(prev, config, now_utc=now)

    colonnes_obligatoires = [
        "t_min_celsius",
        "t_max_celsius",
        "t_moy_celsius",
        "pluie_24h_mm",
        "etp_mm",
        "bilan_eau_cumul_mm",
        # Mildiou actif → ces deux-là doivent figurer.
        "mildiou_heures_humectation",
        "mildiou_smith_period",
    ]
    for col in colonnes_obligatoires:
        assert col in quot.columns, f"Colonne manquante : {col}"


def test_pipeline_complete_compatible_figures_indicateur() -> None:
    """Toutes les colonnes référencées par COURBES existent ou sont absentes
    proprement (pas de KeyError au moment du rendu)."""
    from apps.operationnelle.charts import COURBES
    from apps.operationnelle.indicateurs import calculer_indicateurs_quotidiens

    prev = _prevision_realiste_open_meteo(n_jours=7)
    config = _config_reelle()
    quot = calculer_indicateurs_quotidiens(
        prev, config, now_utc=pd.Timestamp("2026-06-01 00:00", tz="UTC")
    )
    # On itère comme le ferait l'app : seul un sous-ensemble doit avoir
    # accès aux courbes (les colonnes absentes sont silencieuses).
    for cfg in COURBES:
        if cfg.colonne in quot.columns:
            # Pas de NaN ininterprétable dans la colonne.
            assert quot[cfg.colonne].notna().any(), f"Colonne {cfg.colonne} tout NaN"


def test_pipeline_complete_bilan_tunnel_marche_avec_data_realiste() -> None:
    """Le bilan tunnel doit pouvoir tourner sur la même prevision."""
    from apps.operationnelle.charts import bilan_culture_carry_over
    from apps.operationnelle.indicateurs import calculer_indicateurs_quotidiens

    prev = _prevision_realiste_open_meteo(n_jours=7)
    config = _config_reelle()
    quot = calculer_indicateurs_quotidiens(
        prev, config, now_utc=pd.Timestamp("2026-06-01 00:00", tz="UTC")
    )
    bilan = bilan_culture_carry_over(
        quot,
        texture="Terres limono-argileuses",
        fraction_cailloux=0.05,
        culture="Tomate",
        stade="De la plantation à la reprise",
        fraction_ru_remplie_initial=0.7,
        ru_vers_rfu=0.6,
        seuil_irrigation_mm=10.0,
        k_etp_ratio=1.0,
        inclure_pluie=True,
    )
    assert "ru_remplie_avant_mm" in bilan.columns
    assert len(bilan) == len(quot)
