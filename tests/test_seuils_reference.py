"""Tests `meteo_socle.indices.seuils_reference`.

Vérifie surtout les **bornes exactes** des indices MF (≤ pour le gel, >
strict pour les paliers de chaleur, ≥ pour la nuit tropicale) et le fait
qu'on ne renvoie que le palier de chaleur le plus haut.
"""

from __future__ import annotations

from meteo_socle.indices.seuils_reference import (
    LABEL_FORTE_CHALEUR,
    LABEL_GEL,
    LABEL_JOURNEE_CHAUDE,
    LABEL_NUIT_TROPICALE,
    LABEL_TRES_FORTE_CHALEUR,
    etiquettes_temperature,
)


def test_gel_borne_incluse() -> None:
    # Gel = T° min ≤ 0 (0 inclus, juste au-dessus exclu).
    assert etiquettes_temperature(0.0, 10.0) == [LABEL_GEL]
    assert etiquettes_temperature(-3.0, 10.0) == [LABEL_GEL]
    assert etiquettes_temperature(0.1, 10.0) == []


def test_nuit_tropicale_borne_incluse() -> None:
    # Nuit tropicale = T° min ≥ 20 (20 inclus, juste en dessous exclu).
    assert etiquettes_temperature(20.0, 24.0) == [LABEL_NUIT_TROPICALE]
    assert etiquettes_temperature(19.9, 24.0) == []


def test_paliers_chaleur_strictement_superieurs() -> None:
    # Bornes strictes : 25/30/35 pile ne déclenchent pas.
    assert etiquettes_temperature(12.0, 25.0) == []
    assert etiquettes_temperature(12.0, 25.1) == [LABEL_JOURNEE_CHAUDE]
    assert etiquettes_temperature(12.0, 30.0) == [LABEL_JOURNEE_CHAUDE]
    assert etiquettes_temperature(12.0, 30.1) == [LABEL_FORTE_CHALEUR]
    assert etiquettes_temperature(12.0, 35.0) == [LABEL_FORTE_CHALEUR]
    assert etiquettes_temperature(12.0, 35.1) == [LABEL_TRES_FORTE_CHALEUR]


def test_un_seul_palier_chaleur_le_plus_haut() -> None:
    # On n'empile pas journée chaude · forte chaleur · très forte.
    labels = etiquettes_temperature(12.0, 38.0)
    assert labels == [LABEL_TRES_FORTE_CHALEUR]


def test_combinaison_min_et_max() -> None:
    # Une journée peut cumuler un libellé « min » et un libellé « max ».
    labels = etiquettes_temperature(21.0, 36.0)
    assert labels == [LABEL_NUIT_TROPICALE, LABEL_TRES_FORTE_CHALEUR]


def test_journee_neutre_aucun_label() -> None:
    assert etiquettes_temperature(8.0, 18.0) == []


def test_valeurs_indisponibles() -> None:
    assert etiquettes_temperature(None, None) == []
    assert etiquettes_temperature(float("nan"), float("nan")) == []
    # Un côté disponible, l'autre non.
    assert etiquettes_temperature(-1.0, float("nan")) == [LABEL_GEL]
    assert etiquettes_temperature(None, 31.0) == [LABEL_FORTE_CHALEUR]
