"""Tests d'intégration offline de la section « La semaine » du mail Veille.

Exerce le pipeline complet de la Partie 2 (fusion de l'ancienne App 2) avec une
source Single Runs synthétique injectée — zéro réseau :

1. ``executer_semaine`` : fetch (stub) → agrégation tendance + guides → HTML.
2. ``executer_veille`` matin : fusion 48 h (MF mocké) + semaine, vérifie l'ordre
   des sections dans le HTML final (guides/tendance → cartes → seuils en bas).

Aurait attrapé un oubli de conversion d'unités (fixtures en unités socle : K,
m/s, fraction HR) ou un décrochage de l'assemblage des deux parties.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


class _StubSingleRuns:
    """Source Single Runs synthétique : un run = N j horaires en unités socle."""

    def obtenir_run(self, modele, run_utc, latitude, longitude, horizon_jours, variables):
        idx = pd.date_range(run_utc, periods=horizon_jours * 24, freq="h", tz="UTC")
        n = len(idx)
        # Cycle diurne doux (~12-18 °C), climat breton de juin → pas de gel.
        t_c = 15.0 + 4.0 * np.sin(np.linspace(0, 2 * np.pi * horizon_jours, n))
        return pd.DataFrame(
            {
                "temperature_2m": t_c + 273.15,  # K (unité socle)
                "humidite_relative": np.full(n, 0.7),  # fraction 0-1
                "precipitation": np.full(n, 0.3),  # mm/h
                "vitesse_vent_10m": np.full(n, 4.0),  # m/s
                "rafales_vent_10m": np.full(n, 8.0),  # m/s
                "direction_vent_deg": np.full(n, 230.0),
                "rayonnement_global": np.maximum(
                    0, 500 * np.sin(np.linspace(0, 2 * np.pi * horizon_jours, n))
                ),
            },
            index=idx,
        )

    def obtenir_proba_ensemble(self, latitude, longitude, horizon_jours, past_days=0):
        return None  # proba omise (dégradation gracieuse testée par ailleurs)


def _config_op() -> dict:
    import yaml

    with open(REPO_ROOT / "config" / "operationnelle.yaml") as f:
        return yaml.safe_load(f)


def test_executer_semaine_produit_les_blocs_attendus() -> None:
    from apps.veille.semaine import executer_semaine

    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")  # créneau matin
    res = executer_semaine(_config_op(), now, source=_StubSingleRuns(), fetch_cartes=False)
    assert res is not None, "La section semaine ne doit pas échouer avec une source valide."
    html = res["guides_tendance_html"]
    assert "La semaine" in html
    assert "Tendance jusqu'à" in html
    assert "Guides de décision de la semaine" in html
    # Bi-modèle empilé : la légende ARPEGE/ECMWF est rappelée une fois.
    assert "ARPEGE" in html and "ECMWF" in html
    # Cartes désactivées (offline) → pas de série, mais clé présente.
    assert res["cartes_geo"] is None
    assert "Sources" in res["sources_html"]
    assert "GUIDES DE DÉCISION" in res["texte"]


def test_executer_semaine_tendance_demarre_aujourdhui() -> None:
    """La tendance écarte le bout de passé du run ECMWF 12Z J-1 (jour_min)."""
    from apps.veille.semaine import executer_semaine

    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")
    res = executer_semaine(_config_op(), now, source=_StubSingleRuns(), fetch_cartes=False)
    html = res["guides_tendance_html"]
    # 14/06 (J-1) ne doit pas apparaître comme en-tête de jour ; 15/06 oui.
    assert "15/06" in html
    assert "Sam. 14/06" not in html


def _prevision_mf_synthetique():
    from meteo_socle.sources.meteofrance_officiel import PrevisionMF

    idx = pd.date_range("2026-06-15 00:00", periods=48, freq="h", tz="UTC")
    n = len(idx)
    df = pd.DataFrame(
        {
            "temperature_2m": np.full(n, 15.0 + 273.15),
            "humidite_relative": np.full(n, 0.7),
            "precipitation": np.full(n, 0.0),
            "probabilite_pluie_pct": np.full(n, 0.0),
            "vitesse_vent_10m": np.full(n, 5.0),
            "rafales_vent_10m": np.full(n, 9.0),
            "direction_vent_deg": np.full(n, 270.0),
            "cloud_cover": np.full(n, 0.5),
            "weather_code": pd.array([1] * n, dtype="Int64"),
        },
        index=idx,
    )
    return PrevisionMF(
        df=df,
        updated_on=pd.Timestamp("2026-06-15 05:30", tz="UTC"),
        position={"name": "Sains", "timezone": "Europe/Paris"},
    )


def test_executer_veille_matin_fusionne_48h_et_semaine(tmp_path: Path) -> None:
    """Mail matin complet (preview) : 48 h MF + semaine, ordre des sections correct."""
    from apps.veille.__main__ import executer_veille
    from apps.veille.config import load_config

    config = load_config()
    config["diffusion"]["envoi_reel"] = False
    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")
    mock_mf = MagicMock()
    mock_mf.obtenir_prevision.return_value = _prevision_mf_synthetique()
    out = tmp_path / "mail_matin.html"

    code = executer_veille(
        config,
        secrets=None,
        source=mock_mf,
        now_utc=now,
        preview_path=out,
        semaine_source=_StubSingleRuns(),
        fetch_cartes_semaine=False,
    )
    assert code == 0
    html = out.read_text(encoding="utf-8")

    # Les deux parties sont présentes.
    assert "Prévision Météo-France officielle" in html  # Partie 1
    assert "La semaine" in html  # Partie 2
    # Ordre : 48 h → La semaine → Situation synoptique → Seuils (tout en bas).
    i_mf = html.find("Prévision Météo-France officielle")
    i_sem = html.find("La semaine")
    # Ancre ASCII fiable du bloc seuils (bas de mail) : terme propre aux seuils.
    i_seuils = html.find("Guides de la semaine")
    assert i_mf < i_sem < i_seuils, (
        f"Ordre des sections inattendu : mf={i_mf} sem={i_sem} seuils={i_seuils}"
    )
    # Localisation : lieu général dans le titre, point de grille MF en sous-section.
    assert "Pleine-Fougères" in html
    assert "point le plus proche : Sains" in html


def test_regroupement_cartes_synoptiques() -> None:
    """Toutes les cartes regroupées (offline) : Met Office -> AROME -> ARPEGE J+3/J+4."""
    from apps.operationnelle.cartes_geo import CarteGeo, CartesGeoSerie
    from apps.veille.cartes_synoptiques import CartesGrille, CarteSynoptique
    from apps.veille.email import _bloc_cartes_synoptiques

    run = pd.Timestamp("2026-06-15 00:00", tz="UTC")
    uri = "data:image/jpeg;base64,AAAA"
    grille = CartesGrille(
        metoffice=[
            CarteSynoptique("metoffice", run, run + pd.Timedelta(hours=h), uri) for h in (0, 12)
        ],
        arome=[CarteSynoptique("arome", run, run + pd.Timedelta(hours=h), uri) for h in (6, 18)],
    )
    serie = CartesGeoSerie(
        cartes=[CarteGeo(run, run + pd.Timedelta(hours=h), h, uri) for h in (72, 96)]
    )
    html = _bloc_cartes_synoptiques(grille, cartes_longue=serie)
    assert "Situation synoptique" in html
    i_mo = html.find("Met Office")
    i_ar = html.find("AROME 1.3")
    i_arp = html.find("ARPEGE-Europe")
    assert -1 < i_mo < i_ar < i_arp, f"Ordre cartes : mo={i_mo} arome={i_ar} arpege={i_arp}"


def test_executer_veille_apres_midi_sans_semaine(tmp_path: Path) -> None:
    """L'après-midi, la section semaine n'est PAS ajoutée (48 h seul)."""
    from apps.veille.__main__ import executer_veille
    from apps.veille.config import load_config

    config = load_config()
    config["diffusion"]["envoi_reel"] = False
    now = pd.Timestamp("2026-06-15 17:30", tz="UTC")  # après-midi
    mock_mf = MagicMock()
    mock_mf.obtenir_prevision.return_value = _prevision_mf_synthetique()
    out = tmp_path / "mail_apresmidi.html"

    code = executer_veille(
        config,
        secrets=None,
        source=mock_mf,
        now_utc=now,
        preview_path=out,
        semaine_source=_StubSingleRuns(),
        fetch_cartes_semaine=False,
    )
    assert code == 0
    html = out.read_text(encoding="utf-8")
    assert "Prévision Météo-France officielle" in html
    assert "La semaine" not in html
    assert "Tendance jusqu'à 10 jours" not in html
