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
