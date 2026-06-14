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
                "cloud_cover": np.full(n, 0.5),  # fraction 0-1 (nébulosité)
                "rayonnement_global": np.maximum(
                    0, 500 * np.sin(np.linspace(0, 2 * np.pi * horizon_jours, n))
                ),
            },
            index=idx,
        )


class _StubArpegeMuet(_StubSingleRuns):
    """ARPEGE indisponible (run non publié → None), ECMWF normal."""

    def obtenir_run(self, modele, run_utc, latitude, longitude, horizon_jours, variables):
        from meteo_socle.sources.openmeteo_runs import ARPEGE

        if modele == ARPEGE:
            return None
        return super().obtenir_run(modele, run_utc, latitude, longitude, horizon_jours, variables)


class _StubArpegeTronque(_StubSingleRuns):
    """ARPEGE publié partiellement : données s'arrêtant bien avant l'horizon."""

    def obtenir_run(self, modele, run_utc, latitude, longitude, horizon_jours, variables):
        from meteo_socle.sources.openmeteo_runs import ARPEGE

        df = super().obtenir_run(modele, run_utc, latitude, longitude, horizon_jours, variables)
        if modele == ARPEGE:
            return df.iloc[:36]  # ~1,5 j au lieu de horizon_court → run tronqué
        return df


class _StubTousMuets:
    """Aucun modèle disponible (double coupure Open-Meteo)."""

    def obtenir_run(self, *args, **kwargs):
        return None


class _StubArpegeMfDirect:
    """Stub MeteoFranceArpege : df horaire en unités socle (rayonnement_global J/m²/h)."""

    def obtenir_run(self, run_utc, latitude, longitude, horizon_jours, cache_dir=None):
        idx = pd.date_range(run_utc, periods=horizon_jours * 24 + 1, freq="h", tz="UTC")
        n = len(idx)
        cycle = np.sin(np.linspace(0, 2 * np.pi * horizon_jours, n))
        return pd.DataFrame(
            {
                "temperature_2m": 15.0 + 4.0 * cycle + 273.15,  # K
                "humidite_relative": np.full(n, 0.7),  # fraction
                "precipitation": np.full(n, 0.1),  # mm
                "rafales_vent_10m": np.full(n, 8.0),  # m/s
                "cloud_cover": np.full(n, 0.5),  # fraction
                "rayonnement_global": np.maximum(0.0, 2.0e6 * cycle),  # J/m²/h
                "vitesse_vent_10m": np.full(n, 4.0),  # m/s
                "direction_vent_deg": np.full(n, 230.0),
            },
            index=idx,
        )


class _StubArpegeMfMuet:
    """Stub MeteoFranceArpege indisponible → cascade ECMWF (flag MF direct ON)."""

    def obtenir_run(self, *args, **kwargs):
        from meteo_socle.sources.meteofrance_arpege import ArpegeIndisponibleError

        raise ArpegeIndisponibleError("stub muet")


class _StubEcmwfOpendata:
    """Stub EcmwfOpendata : df horaire en unités socle (rafales pleines)."""

    def obtenir_run(self, run_utc, latitude, longitude, horizon_jours, cache_dir=None):
        idx = pd.date_range(run_utc, periods=horizon_jours * 24 + 1, freq="h", tz="UTC")
        n = len(idx)
        cycle = np.sin(np.linspace(0, 2 * np.pi * horizon_jours, n))
        return pd.DataFrame(
            {
                "temperature_2m": 16.0 + 4.0 * cycle + 273.15,  # K
                "humidite_relative": np.full(n, 0.72),  # fraction
                "precipitation": np.full(n, 0.0),  # mm
                "rafales_vent_10m": np.full(n, 9.0),  # m/s (pleines, le gain opendata)
                "cloud_cover": np.full(n, 0.4),  # fraction
                "rayonnement_global": np.maximum(0.0, 2.2e6 * cycle),  # J/m²/h
                "vitesse_vent_10m": np.full(n, 4.5),  # m/s
                "direction_vent_deg": np.full(n, 250.0),
            },
            index=idx,
        )


class _StubEcmwfMuet:
    """Stub EcmwfOpendata indisponible → cascade (flag opendata ON)."""

    def obtenir_run(self, *args, **kwargs):
        from meteo_socle.sources.ecmwf_opendata import EcmwfIndisponibleError

        raise EcmwfIndisponibleError("stub muet")


def _config_op() -> dict:
    import yaml

    with open(REPO_ROOT / "config" / "operationnelle.yaml") as f:
        cfg = yaml.safe_load(f)
    # Tests de la voie Open-Meteo (source injectée) : on neutralise les flags directs
    # (activés/à activer en config prod). Les tests dédiés les repassent à True + stub.
    cfg["source_meteo"]["arpege_mf_direct"] = False
    cfg["source_meteo"]["ecmwf_opendata_direct"] = False
    return cfg


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


def test_executer_semaine_proba_mf_autonome() -> None:
    """La proba MF (signal autonome) est agrégée par fenêtre et affichée."""
    from apps.veille.semaine import executer_semaine

    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")
    # Bins 6 h UTC sur 10 j, valeur distinctive 70 %.
    bins = pd.Series(
        70.0,
        index=pd.date_range("2026-06-15 00:00", periods=10 * 4, freq="6h", tz="UTC"),
    )
    res = executer_semaine(
        _config_op(), now, source=_StubSingleRuns(), fetch_cartes=False, proba_mf=bins
    )
    assert res is not None
    assert "70%" in res["guides_tendance_html"]
    # Légende relabellée (plus « ECMWF » pour la proba).
    assert "MF officielle" in res["guides_tendance_html"]


def test_executer_semaine_sans_proba_mf_cellules_vides() -> None:
    """proba_mf absente (repli) → cellules sans proba (dégradation gracieuse).

    La légende contient « % » (« proba pluie (%…) ») : on cible donc la
    **cellule proba** (slot ``font-size:10px`` à gauche du picto), qui doit
    être vide — pas un « NN% ».
    """
    import re

    from apps.veille.semaine import executer_semaine

    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")
    res = executer_semaine(
        _config_op(), now, source=_StubSingleRuns(), fetch_cartes=False, proba_mf=None
    )
    assert res is not None
    cellule_proba_remplie = re.compile(r"font-size:10px;[^>]*>\s*\d+%\s*</td>")
    assert not cellule_proba_remplie.search(res["guides_tendance_html"])


def test_executer_semaine_arpege_tronque_anomalie_visible() -> None:
    """Run ARPEGE partiel (tronqué) → anomalie VISIBLE (pas une absence muette).

    Distinction du principe « jamais de fausse valeur » : une absence anormale
    (trou/troncature) doit apparaître clairement, contrairement à la 1re nuit
    incomplète (absence normale, silencieuse)."""
    from apps.veille.semaine import executer_semaine

    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")
    res = executer_semaine(_config_op(), now, source=_StubArpegeTronque(), fetch_cartes=False)
    assert res is not None
    resumes = " | ".join(a.resume for a in res["anomalies"])
    assert "partiellement" in resumes.lower(), f"anomalie troncature absente : {resumes}"
    # La note inline (visible en tête de section) signale l'anomalie.
    assert "partiellement" in res["guides_tendance_html"].lower()


def test_fmt_vent_combine_degrade_si_rafale_manquante() -> None:
    """Rafale absente → on garde moyenne + direction (jamais cacher le vrai)."""
    from apps.operationnelle.tendances import CelluleFenetre
    from apps.veille.semaine import _fmt_vent_combine

    def _cell(vent_moy, rafales):
        return CelluleFenetre(
            t_mean=15.0,
            t_extreme=18.0,
            pluie_mm=0.0,
            prob_pluie_pct=float("nan"),
            vent_moy_kmh=vent_moy,
            rafales_max_kmh=rafales,
            direction_cardinal="O",
            direction_deg=270.0,
            etp_mm=float("nan"),
            nebulosite_pct=50.0,
        )

    # Rafale manquante mais moyenne + direction présentes → affichées, pas « — ».
    html = _fmt_vent_combine(_cell(18.0, float("nan")), "jour")
    assert html != "—"
    assert "18" in html  # vent moyen affiché
    assert "–" in html  # placeholder rafale (et non une fausse valeur)
    # Vent moyen absent → cellule complète « — » (rien de fiable à montrer).
    assert _fmt_vent_combine(_cell(float("nan"), float("nan")), "jour") == "—"


def test_executer_semaine_tendance_demarre_aujourdhui() -> None:
    """La tendance écarte le bout de passé du run ECMWF 12Z J-1 (jour_min)."""
    from apps.veille.semaine import executer_semaine

    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")
    res = executer_semaine(_config_op(), now, source=_StubSingleRuns(), fetch_cartes=False)
    html = res["guides_tendance_html"]
    # 14/06 (J-1) ne doit pas apparaître comme en-tête de jour ; 15/06 oui.
    assert "15/06" in html
    assert "Sam. 14/06" not in html


def test_executer_semaine_fallback_arpege_vers_ecmwf() -> None:
    """ARPEGE muet → guides + tendance basés sur ECMWF, anomalie + note inline."""
    from apps.veille.semaine import executer_semaine

    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")
    res = executer_semaine(_config_op(), now, source=_StubArpegeMuet(), fetch_cartes=False)
    assert res is not None
    anomalies = res["anomalies"]
    assert any("ARPEGE indisponible" in a.resume for a in anomalies)
    assert any("repli sur ECMWF" in a.resume for a in anomalies)
    html = res["guides_tendance_html"]
    # Note inline (renvoi au rapport de bug) + guides/tendance toujours produits.
    assert "rapport de bug" in html.lower()
    assert "Guides de décision de la semaine" in html
    assert "Tendance jusqu'à" in html


def test_executer_semaine_arpege_mf_direct() -> None:
    """Flag arpege_mf_direct → ARPEGE via la source MF ; semaine composée, sans anomalie."""
    from apps.veille.semaine import executer_semaine

    cfg = _config_op()
    cfg["source_meteo"]["arpege_mf_direct"] = True
    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")
    res = executer_semaine(
        cfg,
        now,
        source=_StubSingleRuns(),  # ECMWF (tendance longue)
        fetch_cartes=False,
        source_arpege_mf=_StubArpegeMfDirect(),  # ARPEGE direct MF
    )
    assert res is not None
    html = res["guides_tendance_html"]
    assert "La semaine" in html
    assert "Guides de décision de la semaine" in html
    assert not any("ARPEGE indisponible" in a.resume for a in res["anomalies"])
    # Provenance correcte dans le pied (pas de fausse étiquette « Open-Meteo »).
    assert "MF Données Publiques" in res["sources_html"]


def test_executer_semaine_ecmwf_opendata_direct() -> None:
    """Flag ecmwf_opendata_direct → ECMWF via Open Data ; semaine composée, sans anomalie."""
    from apps.veille.semaine import executer_semaine

    cfg = _config_op()
    cfg["source_meteo"]["ecmwf_opendata_direct"] = True
    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")
    res = executer_semaine(
        cfg,
        now,
        source=_StubSingleRuns(),  # ARPEGE (court terme) via Open-Meteo
        fetch_cartes=False,
        source_ecmwf_opendata=_StubEcmwfOpendata(),  # ECMWF direct Open Data
    )
    assert res is not None
    assert "La semaine" in res["guides_tendance_html"]
    assert not any("ECMWF indisponible" in a.resume for a in res["anomalies"])
    # Provenance correcte : ECMWF Open Data, pas « Open-Meteo Single Runs ».
    assert "ECMWF Open Data" in res["sources_html"]


def test_executer_semaine_ecmwf_opendata_muet_cascade() -> None:
    """ECMWF Open Data muet (flag ON) → cascade : tendance limitée à ARPEGE, anomalie."""
    from apps.veille.semaine import executer_semaine

    cfg = _config_op()
    cfg["source_meteo"]["ecmwf_opendata_direct"] = True
    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")
    res = executer_semaine(
        cfg,
        now,
        source=_StubSingleRuns(),  # ARPEGE dispo
        fetch_cartes=False,
        source_ecmwf_opendata=_StubEcmwfMuet(),
    )
    assert res is not None
    assert any("ECMWF indisponible" in a.resume for a in res["anomalies"])


def test_executer_semaine_bandeau_si_double_coupure() -> None:
    """ARPEGE et ECMWF muets → bandeau d'indisponibilité + 2 anomalies."""
    from apps.veille.semaine import executer_semaine

    now = pd.Timestamp("2026-06-15 06:00", tz="UTC")
    res = executer_semaine(_config_op(), now, source=_StubTousMuets(), fetch_cartes=False)
    assert res is not None
    assert "indisponible" in res["guides_tendance_html"].lower()
    assert len(res["anomalies"]) == 2  # ARPEGE + ECMWF


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
    # Proba MF par bin (6 h UTC) sur 10 j, valeur distinctive 60 % → doit
    # remonter dans la section semaine (signal autonome, en tête de cellule).
    bins_idx = pd.date_range("2026-06-15 00:00", periods=10 * 4, freq="6h", tz="UTC")
    proba_bins = pd.Series(60.0, index=bins_idx, name="probabilite_pluie_pct")
    return PrevisionMF(
        df=df,
        updated_on=pd.Timestamp("2026-06-15 05:30", tz="UTC"),
        position={"name": "Sains", "timezone": "Europe/Paris"},
        proba_bins=proba_bins,
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
        source_arpege_mf=_StubArpegeMfDirect(),  # flag MF direct ON en config prod
        source_ecmwf_opendata=_StubEcmwfOpendata(),  # flag ECMWF opendata ON en config prod
    )
    assert code == 0
    html = out.read_text(encoding="utf-8")

    # Les deux parties sont présentes.
    assert "Prévision Météo-France officielle" in html  # Partie 1
    assert "La semaine" in html  # Partie 2
    # Ordre : 48 h → La semaine → Situation synoptique → Seuils (tout en bas).
    i_mf = html.find("Prévision Météo-France officielle")
    i_sem = html.find("La semaine")
    # Ancre du bloc seuils (juste après les sources, bas de mail).
    i_seuils = html.find("Seuils des guides de la semaine")
    assert i_mf < i_sem < i_seuils, (
        f"Ordre des sections inattendu : mf={i_mf} sem={i_sem} seuils={i_seuils}"
    )
    # Localisation : lieu général dans le titre, point de grille MF en sous-section.
    assert "Pleine-Fougères" in html
    assert "point le plus proche : Sains" in html
    # Proba MF autonome (60 % dans la prévi synthétique) remontée dans la semaine.
    assert "60%" in html[i_sem:i_seuils]
    assert "MF officielle" in html  # légende proba relabellée


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


def test_executer_veille_apres_midi_avec_semaine_rappel(tmp_path: Path) -> None:
    """L'après-midi : 48 h actualisé + semaine du matin rappelée (« Pour rappel »)."""
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
        source_arpege_mf=_StubArpegeMfDirect(),
        source_ecmwf_opendata=_StubEcmwfOpendata(),
    )
    assert code == 0
    html = out.read_text(encoding="utf-8")
    assert "Prévision Météo-France officielle" in html
    # La semaine est désormais présente l'après-midi, étiquetée « pour rappel ».
    assert "La semaine" in html
    assert "Tendance jusqu'à 10 jours" in html
    assert "Pour rappel" in html


def test_executer_veille_mail_echec_si_mf_et_semaine_muets(tmp_path: Path) -> None:
    """Dernier recours (fallback_mf) : MF muette ET semaine muette → mail d'échec HTML.

    Plus de repli 48 h : MF injoignable → 48 h omise. Mais si la semaine est elle
    aussi vide (les deux modèles muets), il ne reste rien d'utile → vrai échec (on
    ne livre jamais un mail vide). L'échec n'est notifié qu'en dernier recours (pas
    sur les essais intermédiaires, cf. test_executer_veille_mf_muette_sans_repli_pas_de_mail) ;
    le HTML d'échec porte l'étape + le type + le message de l'exception pour le debug.
    """
    from apps.veille.__main__ import executer_veille
    from apps.veille.config import load_config
    from meteo_socle.sources.meteofrance_officiel import PrevisionIndisponibleError

    config = load_config()
    config["diffusion"]["envoi_reel"] = False
    mock_mf = MagicMock()
    mock_mf.obtenir_prevision.side_effect = PrevisionIndisponibleError(
        "Prévision MF inaccessible : connect timeout"
    )
    out = tmp_path / "echec.html"
    # Les deux modèles de la semaine muets aussi (flags directs ON en config prod) →
    # semaine vide → vrai échec total.
    code = executer_veille(
        config,
        secrets=None,
        source=mock_mf,
        now_utc=pd.Timestamp("2026-06-15 06:00", tz="UTC"),
        preview_path=out,
        source_arpege_mf=_StubArpegeMfMuet(),
        source_ecmwf_opendata=_StubEcmwfMuet(),
        fetch_cartes_semaine=False,
        fallback_mf=True,
    )
    assert code == 2
    html = out.read_text(encoding="utf-8")
    assert "échec" in html.lower()
    assert "PrevisionIndisponibleError" in html  # type d'exception (debug)
    assert "connect timeout" in html  # message (debug)
    assert "semaine aussi indisponible" in html  # étape (debug)


def test_executer_veille_mf_muette_sans_repli_pas_de_mail(tmp_path: Path) -> None:
    """Essai intermédiaire (sans fallback_mf) : MF muette → code 2 SANS écrire d'échec."""
    from apps.veille.__main__ import executer_veille
    from apps.veille.config import load_config
    from meteo_socle.sources.meteofrance_officiel import PrevisionIndisponibleError

    config = load_config()
    config["diffusion"]["envoi_reel"] = False
    mock_mf = MagicMock()
    mock_mf.obtenir_prevision.side_effect = PrevisionIndisponibleError("connect timeout")
    out = tmp_path / "echec.html"
    code = executer_veille(
        config,
        secrets=None,
        source=mock_mf,
        now_utc=pd.Timestamp("2026-06-15 06:00", tz="UTC"),
        preview_path=out,
        fallback_mf=False,
    )
    assert code == 2
    assert not out.exists()  # aucun mail d'échec écrit → pas de spam


def test_executer_veille_matin_rapport_bug_si_arpege_muet(tmp_path: Path) -> None:
    """Mail matin complet : ARPEGE muet → repli ECMWF + rapport de bug en bas."""
    from apps.veille.__main__ import executer_veille
    from apps.veille.config import load_config

    config = load_config()
    config["diffusion"]["envoi_reel"] = False
    mock_mf = MagicMock()
    mock_mf.obtenir_prevision.return_value = _prevision_mf_synthetique()
    out = tmp_path / "matin_arpege_muet.html"
    code = executer_veille(
        config,
        secrets=None,
        source=mock_mf,
        now_utc=pd.Timestamp("2026-06-15 06:00", tz="UTC"),
        preview_path=out,
        semaine_source=_StubSingleRuns(),
        source_arpege_mf=_StubArpegeMfMuet(),  # ARPEGE direct muet → cascade ECMWF
        source_ecmwf_opendata=_StubEcmwfOpendata(),  # ECMWF dispo (le repli de la semaine)
        fetch_cartes_semaine=False,
    )
    assert code == 0
    html = out.read_text(encoding="utf-8")
    assert "La semaine" in html  # section présente (repli ECMWF)
    assert "Rapport de bug" in html  # rapport en fin de mail
    assert "ARPEGE indisponible" in html


def test_executer_veille_mf_indispo_omet_48h_envoie_semaine(tmp_path: Path) -> None:
    """MF injoignable + fallback_mf : la partie 48 h est OMISE (plus de repli ARPEGE),
    le mail part avec la seule section « La semaine » + rapport de bug l'expliquant."""
    from apps.veille.__main__ import executer_veille
    from apps.veille.config import load_config
    from meteo_socle.sources.meteofrance_officiel import PrevisionIndisponibleError

    config = load_config()
    config["diffusion"]["envoi_reel"] = False
    mock_mf = MagicMock()
    mock_mf.obtenir_prevision.side_effect = PrevisionIndisponibleError("MF connect timeout")
    out = tmp_path / "sans_48h.html"
    code = executer_veille(
        config,
        secrets=None,
        source=mock_mf,
        now_utc=pd.Timestamp("2026-06-15 06:00", tz="UTC"),
        preview_path=out,
        source_arpege_mf=_StubArpegeMfDirect(),  # ARPEGE direct dispo → semaine OK
        source_ecmwf_opendata=_StubEcmwfOpendata(),
        fetch_cartes_semaine=False,
        fallback_mf=True,
    )
    assert code == 0  # mail envoyé malgré MF muette
    html = out.read_text(encoding="utf-8")
    # Plus aucune section / label de prévision MF 48 h, ni de « repli » inventé.
    assert "Prévision Météo-France officielle" not in html
    assert "Prévision ARPEGE-Europe" not in html
    assert "repli" not in html.lower()
    # La semaine est bien là (porte l'essentiel) + rapport de bug expliquant l'omission.
    assert "La semaine" in html
    assert "Tendance jusqu'à 10 jours" in html
    assert "Rapport de bug" in html
    assert "partie 48 h omise" in html
    # L'intro semaine ne renvoie plus à une « partie 48 h ci-dessus » absente.
    assert "la partie 48 h ci-dessus" not in html
