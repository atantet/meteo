"""Tests des blocs HTML de la grille / tendance du mail Veille (ADR-0014).

La grille est désormais découpée par **périodes de 6 h locales pleines** (plus
d'ETP, plus d'ancrage run) ; le picto vient du ``weather_code`` MF.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _df_socle(periods: int = 48, debut: str = "2026-06-15 00:00", weather: int = 0) -> pd.DataFrame:
    """Prévision horaire synthétique aux colonnes socle (comme la source MF)."""
    idx = pd.date_range(debut, periods=periods, freq="h", tz="UTC")
    n = len(idx)
    return pd.DataFrame(
        {
            "temperature_2m": np.full(n, 288.0),
            "humidite_relative": np.full(n, 0.7),
            "precipitation": np.full(n, 0.0),
            "vitesse_vent_10m": np.full(n, 4.0),
            "rafales_vent_10m": np.full(n, 8.0),
            "direction_vent_deg": np.full(n, 270.0),
            "weather_code": pd.array([weather] * n, dtype="Int64"),
        },
        index=idx,
    )


def test_diagnostic_pictos_loggue_la_nebulosite(caplog) -> None:
    """Calibration : une ligne PICTO-DIAG par tranche, avec nébulosité moy/max et codes.

    C'est l'info (cloud_cover total/bas/moyen sous-jacent) qui manque pour départager
    « agrégation max trop pessimiste » vs « AROME vraiment couvert » lors des
    comparaisons à MF.com (cf. docs/calibration_pictos.md). Émise au log, pas au mail.
    """
    import logging

    from apps.veille.email import _bloc_grille_indicateurs_48h

    df = _df_socle(48, debut="2026-06-15 00:00")
    df["cloud_cover"] = 0.9  # fraction → 90 %
    df["cloud_cover_low"] = 0.8
    df["cloud_cover_mid"] = 0.3
    with caplog.at_level(logging.INFO, logger="apps.veille.email"):
        _bloc_grille_indicateurs_48h(df, tz_locale="UTC")

    diag = [r.getMessage() for r in caplog.records if "PICTO-DIAG" in r.getMessage()]
    assert diag, "au moins une tranche doit être loggée"
    assert any("nébul tot 90/90 bas 80/80 moy 30/30" in m for m in diag)


def test_grille_cap_au_soir_de_j1_apres_midi() -> None:
    """Après-midi : la grille s'arrête au soir de J+1 (pas de J+2).

    L'après-midi, le run AROME atteint J+2 matin — mais la Vigilance (DPVigilance)
    ne couvre que J/J+1, donc le picto orage y serait aveugle. On cape donc le rendu
    au soir de J+1 (la « semaine » prend le relais). Le cap ne s'applique qu'avec
    l'heure d'envoi (``now_utc``) ; les indicateurs 24/48 h ne sont pas touchés.
    """
    from apps.veille.email import _bloc_grille_indicateurs_48h

    # 56 h depuis mer. 17/06 00 h UTC → couvre la nuit de ven. 19/06 (J+2).
    df = _df_socle(periods=56, debut="2026-06-17 00:00")
    now = pd.Timestamp("2026-06-17 18:30", tz="UTC")  # envoi après-midi (créneau Soir)

    # Sans heure d'envoi (pas de cap) : J+2 (Vendredi) apparaît, la donnée le couvre.
    assert "Vendredi 19/06" in _bloc_grille_indicateurs_48h(df, tz_locale="UTC")

    # Avec l'heure d'envoi : cap au soir de J+1 → Vendredi disparaît, Jeudi reste.
    html = _bloc_grille_indicateurs_48h(df, now_utc=now, tz_locale="UTC")
    assert "Mercredi 17/06" in html  # J (créneau Soir)
    assert "Jeudi 18/06" in html  # J+1 (complet)
    assert "Vendredi 19/06" not in html  # J+2 capé


def test_grille_picto_nuit_pour_fenetre_0_6() -> None:
    """La grille utilise l'icône nuit (lune) pour la fenêtre [0, 6) seulement."""
    from apps.shared.pictograms import icone_base64
    from apps.veille.email import _bloc_grille_indicateurs_48h

    df = _df_socle(48, weather=0)  # ciel clair
    html = _bloc_grille_indicateurs_48h(df, tz_locale="UTC")

    uri_nuit = icone_base64(0, nuit=True)  # clear-night
    uri_jour = icone_base64(0, nuit=False)  # clear-day
    assert uri_nuit != uri_jour
    assert uri_nuit in html  # fenêtre Nuit
    assert uri_jour in html  # autres fenêtres


def test_grille_periodes_pleines_sans_etp() -> None:
    """48 h dès 00:00 (tz=UTC) → 8 périodes pleines (2 j × 4) ; aucun bloc ETP."""
    from apps.veille.email import _bloc_grille_indicateurs_48h

    df = _df_socle(48, weather=0)
    html = _bloc_grille_indicateurs_48h(df, tz_locale="UTC")

    # 8 pictos (Nuit/Matin/Après-midi/Soir × 2 jours).
    assert html.count("data:image") == 8
    assert "Tendance jusqu" in html
    # Plus d'ETP ni de bilan eau dans la Veille (ADR-0014).
    assert "ETP" not in html
    assert "Bilan eau" not in html


def test_grille_exclut_periode_partielle_de_tete() -> None:
    """Données dès 05:00 → la Nuit [0,6) partielle est exclue (— au lieu d'un picto)."""
    from apps.veille.email import _bloc_grille_indicateurs_48h

    df = _df_socle(48, debut="2026-06-15 05:00", weather=0)
    html = _bloc_grille_indicateurs_48h(df, tz_locale="UTC")
    # 1er jour : Matin/Après-midi/Soir pleins (3), Nuit partielle exclue ;
    # 2e jour : 4 pleins ; 3e jour : Nuit (00-04 manquants → partielle). = 7 pictos.
    assert html.count("data:image") == 7


def test_grille_vide_si_none() -> None:
    from apps.veille.email import _bloc_grille_indicateurs_48h

    assert _bloc_grille_indicateurs_48h(None) == ""


def test_tendance_texte_48h_format_lignes() -> None:
    from apps.veille.email import _tendance_texte_48h

    idx = pd.date_range("2026-06-15 00:00", periods=48, freq="h", tz="UTC")
    codes = np.zeros(48, dtype=int)
    codes[13:16] = 63
    df = pd.DataFrame({"weather_code": codes}, index=idx)
    lignes = _tendance_texte_48h(df, tz_locale="Europe/Paris")
    assert len(lignes) == 2
    assert "→" in lignes[0]
    assert "matin" in lignes[0]
    assert "midi" in lignes[0]
    assert "soir" in lignes[0]
    assert "Pluie" in lignes[0]


def test_tendance_texte_48h_fenetre_vide_ne_crashe_pas() -> None:
    from apps.veille.email import _tendance_texte_48h

    idx = pd.date_range("2026-06-15 12:00", periods=48, freq="h", tz="UTC")
    df = pd.DataFrame({"weather_code": np.ones(48, dtype=int)}, index=idx)
    lignes = _tendance_texte_48h(df, tz_locale="UTC")
    assert lignes
    assert "matin" not in lignes[0]
    assert "soir" in lignes[0]


def test_tendance_texte_48h_sans_data_renvoie_vide() -> None:
    from apps.veille.email import _tendance_texte_48h

    assert _tendance_texte_48h(None) == []
    idx = pd.date_range("2026-06-15 00:00", periods=24, freq="h", tz="UTC")
    df = pd.DataFrame({"temperature_2m": [285.0] * 24}, index=idx)
    assert _tendance_texte_48h(df) == []
