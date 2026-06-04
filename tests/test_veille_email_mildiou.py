"""Tests du bloc HTML "Risque maladies" dans le mail Veille."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def test_bloc_pictogrammes_veille_grille_2j_3fenetres() -> None:
    """Le bloc pictos doit produire 6 cellules (2 j × 3 fenêtres)."""
    import numpy as np

    from apps.veille.email import _bloc_pictogrammes_veille

    # 48 h horaires synthétiques avec weather_code = 0 (clair) partout.
    idx = pd.date_range("2026-06-15 00:00", periods=48, freq="h", tz="UTC")
    df = pd.DataFrame({"weather_code": np.zeros(48, dtype=int)}, index=idx)
    html = _bloc_pictogrammes_veille(df, tz_locale="Europe/Paris")
    # 6 pictos = 6 cellules avec data:image inline.
    assert html.count("data:image/png") == 6
    assert "Tendance 48 h" in html
    assert "Matin" in html
    assert "Midi" in html
    assert "Soir" in html


def test_grille_picto_nuit_pour_fenetre_0_6() -> None:
    """La grille 48 h utilise l'icône nuit (lune) pour la fenêtre [0, 6) seulement."""
    from apps.shared.pictograms import icone_base64
    from apps.veille.email import _bloc_grille_indicateurs_48h

    # 48 h de ciel clair (weather_code=0). tz=UTC pour que les heures
    # locales == heures UTC (fenêtre Nuit 0-6 peuplée dès le 1er jour).
    idx = pd.date_range("2026-06-15 00:00", periods=48, freq="h", tz="UTC")
    df = pd.DataFrame({"weather_code": np.zeros(48, dtype=int)}, index=idx)
    now_utc = pd.Timestamp("2026-06-15 00:00", tz="UTC")
    html = _bloc_grille_indicateurs_48h(df, now_utc=now_utc, tz_locale="UTC")

    uri_nuit = icone_base64(0, nuit=True)  # clear-night
    uri_jour = icone_base64(0, nuit=False)  # clear-day
    # Les deux variantes sont bien distinctes (lune ≠ soleil).
    assert uri_nuit != uri_jour
    # La fenêtre Nuit déclenche l'icône nuit ; les autres l'icône jour.
    assert uri_nuit in html
    assert uri_jour in html


def test_grille_apres_midi_ancree_12h_3_dates() -> None:
    """Envoi après-midi : la grille ancre à 12 h et déborde sur une 3ᵉ date.

    Fenêtre [12 h J ; 12 h J+2] → 3 dates (J après-midi/soir, J+1 complet,
    J+2 nuit/matin). Le matin [00 h ; +48 h] n'en couvre que 2.
    """
    from apps.veille.email import _bloc_grille_indicateurs_48h

    # 72 h de ciel clair. tz=UTC → heures locales == heures UTC.
    idx = pd.date_range("2026-06-15 00:00", periods=72, freq="h", tz="UTC")
    df = pd.DataFrame({"weather_code": np.zeros(72, dtype=int)}, index=idx)

    # Après-midi : now 14 h UTC → ancre 12 h UTC le 15.
    html_pm = _bloc_grille_indicateurs_48h(
        df, now_utc=pd.Timestamp("2026-06-15 14:00", tz="UTC"), tz_locale="UTC"
    )
    # 3 dates présentes (15, 16, 17/06).
    assert "15/06" in html_pm and "16/06" in html_pm and "17/06" in html_pm
    # Jour d'ancrage partiel : seulement Après-midi + Soir (2 pictos),
    # J+1 complet (4), J+2 nuit + matin (2) = 8 pictos au total. On compte
    # "data:image" (et non "...png") car la fenêtre Nuit par ciel clair
    # rend une icône SVG (clear-night), pas un PNG.
    assert html_pm.count("data:image") == 8

    # Matin : now 06 h UTC → ancre 00 h UTC le 15 → 2 dates seulement.
    html_matin = _bloc_grille_indicateurs_48h(
        df, now_utc=pd.Timestamp("2026-06-15 06:00", tz="UTC"), tz_locale="UTC"
    )
    assert "17/06" not in html_matin
    assert "15/06" in html_matin and "16/06" in html_matin


def test_grille_apres_midi_etp_jour_nocturne_j_et_j1_pas_j2() -> None:
    """Après-midi : ETP = jour nocturne 24 h (midi→midi) pour J et J+1, pas J+2.

    Deux blocs de 24 h ([12h J ; 12h J+1] et [12h J+1 ; 12h J+2]) → 2 lignes
    ETP complètes. Le 3ᵉ tableau (J+2) n'a pas de ligne ETP (bloc déborderait
    des 48 h). La somme des 2 ETP = ETP du bilan eau 48 h.
    """
    from apps.veille.email import _bloc_grille_indicateurs_48h

    idx = pd.date_range("2026-06-15 00:00", "2026-06-18 23:00", freq="h", tz="UTC")
    df = pd.DataFrame({"weather_code": np.ones(len(idx), dtype=int)}, index=idx)
    etp = pd.Series(0.1, index=idx)  # 0.1 mm/h constant → 2.4 mm / 24 h
    # tz=UTC, now 14 h UTC → ancre 12 h UTC le 15 ; fenêtre [12h15 ; 12h17].
    html = _bloc_grille_indicateurs_48h(
        df, etp_horaire_48h=etp, now_utc=pd.Timestamp("2026-06-15 14:00", tz="UTC"), tz_locale="UTC"
    )
    # 3 dates affichées mais 2 lignes ETP seulement (15 et 16, pas 17),
    # libellées « ETP du jour nocturne » (24 h midi→midi).
    assert "17/06" in html
    assert html.count("ETP du jour nocturne") == 2
    # Chaque jour nocturne complet = 24 × 0.1 = 2.4 mm.
    assert html.count(">2.4<") == 2
    # Bilan eau 48 h : ETP = somme des deux = 4.8 mm.
    assert "ETP = 4.8" in html


def test_grille_matin_etp_2_jours_calendaires() -> None:
    """Matin : 2 lignes ETP (J, J+1), chacune sur le jour calendaire complet."""
    from apps.veille.email import _bloc_grille_indicateurs_48h

    idx = pd.date_range("2026-06-15 00:00", "2026-06-18 23:00", freq="h", tz="UTC")
    df = pd.DataFrame({"weather_code": np.ones(len(idx), dtype=int)}, index=idx)
    etp = pd.Series(0.1, index=idx)
    # now 06 h UTC → ancre 00 h UTC le 15 ; fenêtre [00h15 ; 00h17] = 2 jours.
    html = _bloc_grille_indicateurs_48h(
        df, etp_horaire_48h=etp, now_utc=pd.Timestamp("2026-06-15 06:00", tz="UTC"), tz_locale="UTC"
    )
    assert "17/06" not in html
    # Matin : libellé « ETP du jour » (jour calendaire), pas « nocturne ».
    assert html.count("ETP du jour") == 2
    assert "nocturne" not in html
    assert html.count(">2.4<") == 2


def test_bloc_pictogrammes_veille_vide_sans_weather_code() -> None:
    """Si la prévision n'a pas weather_code, le bloc retourne ''."""
    from apps.veille.email import _bloc_pictogrammes_veille

    idx = pd.date_range("2026-06-15 00:00", periods=48, freq="h", tz="UTC")
    df = pd.DataFrame({"temperature_2m": [285.0] * 48}, index=idx)
    assert _bloc_pictogrammes_veille(df) == ""


def test_bloc_pictogrammes_veille_vide_si_none() -> None:
    from apps.veille.email import _bloc_pictogrammes_veille

    assert _bloc_pictogrammes_veille(None) == ""


def test_tendance_texte_48h_format_lignes() -> None:
    """Tendance texte renvoie 2 lignes (1 par jour) format attendu."""
    import numpy as np

    from apps.veille.email import _tendance_texte_48h

    idx = pd.date_range("2026-06-15 00:00", periods=48, freq="h", tz="UTC")
    codes = np.zeros(48, dtype=int)
    codes[13:16] = 63
    df = pd.DataFrame({"weather_code": codes}, index=idx)
    lignes = _tendance_texte_48h(df, tz_locale="Europe/Paris")
    assert len(lignes) == 2
    # Format : flèches entre fenêtres + libellés FR.
    assert "→" in lignes[0]
    assert "matin" in lignes[0]
    assert "midi" in lignes[0]
    assert "soir" in lignes[0]
    # Pluie modérée sur jour 1 (codes 63 en milieu de journée).
    assert "Pluie" in lignes[0]


def test_tendance_texte_48h_sans_data_renvoie_vide() -> None:
    from apps.veille.email import _tendance_texte_48h

    assert _tendance_texte_48h(None) == []
    # DataFrame sans weather_code.
    idx = pd.date_range("2026-06-15 00:00", periods=24, freq="h", tz="UTC")
    df = pd.DataFrame({"temperature_2m": [285.0] * 24}, index=idx)
    assert _tendance_texte_48h(df) == []


def test_bloc_pictogrammes_priorise_pluie_sur_clair() -> None:
    """Pluie modérée mi-journée → picto pluie, pas clair."""
    import numpy as np

    from apps.veille.email import _bloc_pictogrammes_veille

    idx = pd.date_range("2026-06-15 00:00", periods=48, freq="h", tz="UTC")
    codes = np.zeros(48, dtype=int)
    codes[10:15] = 63  # pluie modérée midi local le 1er jour
    df = pd.DataFrame({"weather_code": codes}, index=idx)
    html = _bloc_pictogrammes_veille(df, tz_locale="Europe/Paris")
    assert "Pluie modérée" in html
