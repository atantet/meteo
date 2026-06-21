"""Tests `apps.shared.pictograms` — mapping WMO + icônes MET Norway (yr)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def test_nom_icone_codes_canoniques() -> None:
    from apps.shared.pictograms import nom_icone

    assert nom_icone(0) == "clearsky_day"
    assert nom_icone(2) == "partlycloudy_day"
    assert nom_icone(3) == "cloudy"
    assert nom_icone(45) == "fog"
    assert nom_icone(63) == "rain"
    assert nom_icone(95) == "rainandthunder"


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
    assert uri.startswith("data:image/svg+xml;base64,")
    assert len(uri) > 100  # SVG encodé non-vide


def test_icone_base64_code_inconnu_renvoie_fallback() -> None:
    from apps.shared.pictograms import icone_base64

    uri = icone_base64(999)
    assert uri.startswith("data:image/png;base64,")


def test_nom_icone_variante_nuit() -> None:
    """Ciel clair / nuageux / averses : jour vs nuit doivent différer (soleil → lune)."""
    from apps.shared.pictograms import nom_icone

    assert nom_icone(0) == "clearsky_day"
    assert nom_icone(0, nuit=True) == "clearsky_night"
    assert nom_icone(2, nuit=True) == "partlycloudy_night"
    assert nom_icone(80, nuit=True) == "lightrainshowers_night"
    assert nom_icone(81, nuit=True) == "rainshowers_night"
    assert nom_icone(85, nuit=True) == "lightsnowshowers_night"


def test_nom_icone_nuit_fallback_pour_codes_sans_variante() -> None:
    """Les codes sans variante nuit (pluie forte, orages) gardent l'icône jour."""
    from apps.shared.pictograms import nom_icone

    # 63 (pluie modérée continue) → pas de variante nuit, retombe sur "rain"
    assert nom_icone(63, nuit=True) == "rain"
    # 95 (orage) → pas de variante nuit
    assert nom_icone(95, nuit=True) == "rainandthunder"


def test_icone_base64_nuit_renvoie_svg_data_uri() -> None:
    """Les variantes nuit sont des SVG → mime image/svg+xml."""
    from apps.shared.pictograms import icone_base64

    uri = icone_base64(0, nuit=True)
    assert uri.startswith("data:image/svg+xml;base64,")
    assert len(uri) > 100


def test_chemin_icone_nuit_existe_pour_codes_principaux() -> None:
    """Toutes les variantes nuit déclarées doivent exister sur disque."""
    from apps.shared.pictograms import WMO_VERS_ICONE_NUIT, chemin_icone

    for code in WMO_VERS_ICONE_NUIT:
        chemin = chemin_icone(code, nuit=True)
        assert chemin.exists(), f"Variante nuit absente pour code {code} : {chemin}"


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


def test_code_dominant_fenetre_garde_fou_eclaircies() -> None:
    """Tranche majoritairement couverte mais avec une éclaircie → pas couvert plein."""
    from apps.shared.pictograms import code_dominant_fenetre

    # Le picto 6 h doit refléter qu'il y a eu du soleil, pas afficher un couvert plein.
    assert code_dominant_fenetre(pd.Series([0, 3, 3, 3, 3, 3])) == 2  # 1 soleil + 5 couvert
    assert code_dominant_fenetre(pd.Series([1, 3, 3, 3])) == 2  # peu nuageux + couvert
    assert code_dominant_fenetre(pd.Series([2, 3, 3, 3])) == 2  # partiel + couvert


def test_code_dominant_fenetre_ciel_representatif() -> None:
    """Ciel sec : niveau moyen représentatif — ne pas sur-couvrir une tranche ensoleillée."""
    from apps.shared.pictograms import code_dominant_fenetre

    assert code_dominant_fenetre(pd.Series([3, 3, 3, 3])) == 3  # tout couvert → couvert
    assert code_dominant_fenetre(pd.Series([0, 0, 0])) == 0  # tout ensoleillé
    # Majoritairement clair + 1-2 h chargées → peu nuageux, PAS partiellement nuageux
    # (régression du biais « tout en ⛅ » vu le 2026-06-21 : matinées à ~20-30 % nuages).
    assert code_dominant_fenetre(pd.Series([0, 0, 0, 0, 2, 1])) == 1  # MF : peu nuageux
    assert code_dominant_fenetre(pd.Series([0, 0, 2, 2, 0, 0])) == 1  # idem


def test_code_dominant_fenetre_evenement_prime_sur_eclaircies() -> None:
    """Une averse (≥ 45) est signalée même s'il y a du soleil dans la fenêtre."""
    from apps.shared.pictograms import code_dominant_fenetre

    # 0 = ensoleillé, 61 = pluie (sev 7) : on ne cache pas l'averse sous des éclaircies.
    assert code_dominant_fenetre(pd.Series([0, 0, 61, 3])) == 61


def test_code_dominant_fenetre_vide_renvoie_none() -> None:
    """Série vide ou tout NaN → None (modèle sans weather_code)."""
    from apps.shared.pictograms import code_dominant_fenetre

    assert code_dominant_fenetre(pd.Series([], dtype=float)) is None
    assert code_dominant_fenetre(pd.Series([float("nan")] * 3)) is None


def test_codes_dominants_par_jour_decoupe_local() -> None:
    """Agrégation diurne (8h-20h) par jour local."""
    import numpy as np

    from apps.shared.pictograms import codes_dominants_par_jour

    # 48 h horaires UTC à partir du 15 juin minuit.
    idx = pd.date_range("2026-06-15 00:00", periods=48, freq="h", tz="UTC")
    codes = np.zeros(48, dtype=int)  # clair partout par défaut
    # Pluie modérée (63) à 13h-15h UTC le 15 juin = 15h-17h Paris.
    codes[13:16] = 63
    df = pd.DataFrame({"weather_code": codes}, index=idx)
    out = codes_dominants_par_jour(df, tz_locale="Europe/Paris")
    # Au moins 2 jours.
    assert len(out) >= 2
    # 1er jour doit montrer pluie (sévérité maxi).
    code_jour1 = out[0][1]
    assert code_jour1 == 63


def test_codes_dominants_par_jour_vide_renvoie_liste_vide() -> None:
    from apps.shared.pictograms import codes_dominants_par_jour

    assert codes_dominants_par_jour(pd.DataFrame()) == []


def test_codes_dominants_par_jour_sans_weather_code_vide() -> None:
    """Si la colonne weather_code n'existe pas, retour vide."""
    from apps.shared.pictograms import codes_dominants_par_jour

    idx = pd.date_range("2026-06-15", periods=24, freq="h", tz="UTC")
    df = pd.DataFrame({"temperature_2m": [285.0] * 24}, index=idx)
    assert codes_dominants_par_jour(df) == []
