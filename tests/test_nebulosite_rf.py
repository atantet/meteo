"""Tests du Random Forest de nébulosité (tranche 6 h, cf. docs/calibration_pictos.md).

Fixtures en unités socle : fraction (0-1) pour les nébulosités/humidité, K
pour la température, mm pour la pluie, m pour la visibilité — pour qu'une
conversion oubliée casse un test plutôt que de passer inaperçue.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _df_socle(n: int = 6, **overrides: float) -> pd.DataFrame:
    """Fenêtre horaire socle synthétique (ciel clair, sec, par défaut)."""
    idx = pd.date_range("2026-09-30 00:00", periods=n, freq="h", tz="UTC")
    base = {
        "cloud_cover": np.full(n, 0.0),
        "cloud_cover_low": np.full(n, 0.0),
        "cloud_cover_mid": np.full(n, 0.0),
        "precipitation": np.full(n, 0.0),
        "temperature_2m": np.full(n, 288.15),  # 15 °C
        "visibilite_m": np.full(n, 20000.0),
        "humidite_relative": np.full(n, 0.6),
    }
    base.update(overrides)
    return pd.DataFrame(base, index=idx)


def test_modele_charge_et_predit_ciel_clair() -> None:
    from meteo_socle.indices.temps_sensible import nebulosite_rf

    code = nebulosite_rf(0.0, 0.0, 0.0, 0.0, 15.0, 20000.0, 0.5)
    assert code in (0, 1)  # ciel dégagé, sec, bonne visibilité → pas "couvert"


def test_modele_predit_couvert_sous_ciel_totalement_bas() -> None:
    from meteo_socle.indices.temps_sensible import nebulosite_rf

    code = nebulosite_rf(100.0, 100.0, 80.0, 0.0, 12.0, 3000.0, 0.95)
    assert code == 3


def test_nebulosite_rf_none_si_une_feature_manque() -> None:
    from meteo_socle.indices.temps_sensible import nebulosite_rf

    assert nebulosite_rf(0.0, 0.0, 0.0, 0.0, 15.0, None, 0.5) is None
    assert nebulosite_rf(0.0, 0.0, 0.0, 0.0, 15.0, float("nan"), 0.5) is None


def test_depuis_fenetre_agrege_correctement() -> None:
    """cc/cc_low/cc_mid moyennés en %, precip/temp/humi moyennés, visi = min."""
    from meteo_socle.indices.temps_sensible import (
        _FEATURES_NEBULOSITE_RF,
        _charger_modele_nebulosite_rf,
        nebulosite_rf_depuis_fenetre,
    )

    sub = _df_socle(
        4,
        cloud_cover=np.array([0.0, 0.2, 0.4, 0.6]),
        visibilite_m=np.array([20000.0, 500.0, 15000.0, 18000.0]),
    )
    code = nebulosite_rf_depuis_fenetre(sub)
    assert code is not None

    # Reproduit l'agrégation attendue et compare à un appel direct.
    from meteo_socle.indices.temps_sensible import nebulosite_rf

    attendu = nebulosite_rf(
        sub["cloud_cover"].mean() * 100.0,
        sub["cloud_cover_low"].mean() * 100.0,
        sub["cloud_cover_mid"].mean() * 100.0,
        sub["precipitation"].mean(),
        sub["temperature_2m"].mean() - 273.15,
        sub["visibilite_m"].min(),
        sub["humidite_relative"].mean(),
    )
    assert code == attendu
    assert _FEATURES_NEBULOSITE_RF  # sanity : ordre des features exposé
    assert _charger_modele_nebulosite_rf() is not None  # modèle bien committé


def test_depuis_fenetre_none_si_colonne_manquante() -> None:
    """Pas de visibilité (ex. legacy PICTO-DIAG) → repli, pas d'exception."""
    from meteo_socle.indices.temps_sensible import nebulosite_rf_depuis_fenetre

    sub = _df_socle().drop(columns=["visibilite_m"])
    assert nebulosite_rf_depuis_fenetre(sub) is None


def test_depuis_fenetre_vide_renvoie_none() -> None:
    from meteo_socle.indices.temps_sensible import nebulosite_rf_depuis_fenetre

    assert nebulosite_rf_depuis_fenetre(pd.DataFrame()) is None


def test_code_dominant_fenetre_utilise_le_rf_si_fourni() -> None:
    """La voie ciel sec retient le RF plutôt que le niveau moyen quand il est fourni."""
    from apps.shared.pictograms import code_dominant_fenetre

    codes = pd.Series([0, 0, 3, 3, 3, 3])  # 1 soleil + 5 couvert → garde-fou éclaircies
    # Sans RF : garde-fou éclaircies → 2 (comportement historique inchangé).
    assert code_dominant_fenetre(codes) == 2
    # Avec RF : la prédiction fournie l'emporte directement.
    assert code_dominant_fenetre(codes, nebulosite_rf=1) == 1


def test_code_dominant_fenetre_evenement_ignore_le_rf() -> None:
    """Un événement (pluie/orage/brouillard) prime toujours sur le RF — jamais caché."""
    from apps.shared.pictograms import code_dominant_fenetre

    codes = pd.Series([0, 0, 61, 3])  # 61 = pluie
    assert code_dominant_fenetre(codes, nebulosite_rf=0) == 61


def test_code_dominant_fenetre_rf_none_retombe_sur_seuillage() -> None:
    from apps.shared.pictograms import code_dominant_fenetre

    codes = pd.Series([0, 0, 0, 0, 2, 1])
    assert code_dominant_fenetre(codes, nebulosite_rf=None) == code_dominant_fenetre(codes)
