"""Tests du bloc HTML "Risque maladies" dans le mail Veille."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


_CONFIG_RM = {
    "alertes": {
        "risque_maladies": {
            "actif": True,
            "t_min_nuit_celsius": 15.0,
            "hr_seuil": 0.90,
            "heures_min": 6,
        }
    }
}


def _prevision_synth(t_celsius: float, hr_fraction: float) -> pd.DataFrame:
    """48 h synthétiques constantes pour test_bloc_risque_maladies."""
    idx = pd.date_range("2026-07-01 00:00", periods=48, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(48, t_celsius + 273.15),
            "humidite_relative": np.full(48, hr_fraction),
        },
        index=idx,
    )


def test_bloc_risque_maladies_conditions_propices() -> None:
    """T_min ≥ 15 °C + HR ≥ 90 % constants → bandeau orange "Conditions propices"."""
    from apps.veille.email import _bloc_risque_maladies

    html = _bloc_risque_maladies(
        _prevision_synth(t_celsius=16.0, hr_fraction=0.95),
        _CONFIG_RM,
        tz_locale="Europe/Paris",
    )
    assert "Risque maladies" in html
    assert "Conditions propices" in html or "conditions propices" in html
    # Bandeau orange (Wong palette E69F00) indique un risque.
    assert "#E69F00" in html


def test_bloc_risque_maladies_pas_de_signal() -> None:
    """Nuit fraîche + air sec → bandeau vert "Pas de signal"."""
    from apps.veille.email import _bloc_risque_maladies

    html = _bloc_risque_maladies(
        _prevision_synth(t_celsius=10.0, hr_fraction=0.50),
        _CONFIG_RM,
        tz_locale="Europe/Paris",
    )
    assert "Risque maladies" in html
    assert "pas de signal" in html.lower()
    # Bandeau vert (Wong palette 009E73) = pas de risque.
    assert "#009E73" in html


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


def test_bloc_risque_maladies_vide_si_inactif() -> None:
    """Si alertes.risque_maladies.actif=False → bloc vide."""
    from apps.veille.email import _bloc_risque_maladies

    config = {"alertes": {"risque_maladies": {"actif": False}}}
    html = _bloc_risque_maladies(
        _prevision_synth(t_celsius=16.0, hr_fraction=0.95),
        config,
    )
    assert html == ""


def test_bloc_risque_maladies_vide_si_prevision_none() -> None:
    """Si prevision_horaire=None → bloc vide (ne casse pas le mail)."""
    from apps.veille.email import _bloc_risque_maladies

    assert _bloc_risque_maladies(None, _CONFIG_RM) == ""
