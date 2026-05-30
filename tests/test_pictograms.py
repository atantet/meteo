"""Tests `apps.shared.pictograms` — mapping WMO + icônes Meteocons."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def test_nom_icone_codes_canoniques() -> None:
    from apps.shared.pictograms import nom_icone

    assert nom_icone(0) == "clear-day"
    assert nom_icone(2) == "partly-cloudy-day"
    assert nom_icone(3) == "overcast-day"
    assert nom_icone(45) == "fog-day"
    assert nom_icone(63) == "rain"
    assert nom_icone(95) == "thunderstorms"


def test_nom_icone_code_inconnu_renvoie_fallback() -> None:
    from apps.shared.pictograms import nom_icone

    assert nom_icone(999) == "not-available"


def test_libelle_fr_canonique() -> None:
    from apps.shared.pictograms import libelle

    assert "clair" in libelle(0).lower()
    assert "pluie" in libelle(63).lower()
    assert "orage" in libelle(95).lower()


def test_chemin_icone_existe_pour_codes_courants() -> None:
    from apps.shared.pictograms import chemin_icone

    for code in (0, 2, 3, 45, 63, 73, 95):
        chemin = chemin_icone(code)
        assert chemin.exists(), f"Icône manquante pour code {code} : {chemin}"


def test_icone_base64_format_data_uri() -> None:
    from apps.shared.pictograms import icone_base64

    uri = icone_base64(0)
    assert uri.startswith("data:image/png;base64,")
    assert len(uri) > 100  # PNG encodé non-vide


def test_icone_base64_code_inconnu_renvoie_fallback() -> None:
    from apps.shared.pictograms import icone_base64

    uri = icone_base64(999)
    assert uri.startswith("data:image/png;base64,")


def test_code_dominant_fenetre_prend_max_severite() -> None:
    from apps.shared.pictograms import code_dominant_fenetre

    # 1 = principalement clair (sev 1), 63 = pluie modérée (sev 8)
    # → on doit retenir 63.
    serie = pd.Series([1, 1, 63, 1, 1])
    assert code_dominant_fenetre(serie) == 63


def test_code_dominant_fenetre_orage_prioritaire() -> None:
    from apps.shared.pictograms import code_dominant_fenetre

    # 95 (orage, sev 10) > 65 (pluie forte, sev 9)
    serie = pd.Series([65, 65, 95, 65])
    assert code_dominant_fenetre(serie) == 95


def test_code_dominant_fenetre_vide_renvoie_0() -> None:
    from apps.shared.pictograms import code_dominant_fenetre

    assert code_dominant_fenetre(pd.Series([], dtype=float)) == 0
    assert code_dominant_fenetre(pd.Series([float("nan")] * 3)) == 0
