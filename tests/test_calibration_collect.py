"""Le dataset de calibration ne doit jamais perdre de lignes quand les logs GH expirent."""

import importlib.util
from pathlib import Path

import pandas as pd

_SPEC = importlib.util.spec_from_file_location(
    "collect", Path(__file__).parent.parent / "calibration" / "collect.py"
)
collect = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(collect)


def _ligne(run_id, jour, fenetre, cc_avg):
    return {
        "run_id": run_id,
        "jour_local": jour,
        "fenetre": fenetre,
        "mf_wmo": 0,
        "cc_avg": cc_avg,
    }


def test_lignes_anciennes_conservees_quand_le_log_a_expire(tmp_path):
    sortie = tmp_path / "dataset.csv"
    pd.DataFrame([_ligne(1, "2026-06-25", "Soir", 84.0)]).to_csv(sortie, index=False)

    nouveau = pd.DataFrame([_ligne(2, "2026-09-24", "Soir", 93.4)])
    fusion = collect._merge_with_existing(nouveau, sortie)

    assert set(fusion["run_id"]) == {1, 2}


def test_aucune_nouvelle_ligne_ne_vide_pas_le_dataset(tmp_path):
    sortie = tmp_path / "dataset.csv"
    pd.DataFrame([_ligne(1, "2026-06-25", "Soir", 84.0)]).to_csv(sortie, index=False)

    fusion = collect._merge_with_existing(pd.DataFrame(), sortie)

    assert len(fusion) == 1


def test_ligne_fraiche_remplace_l_ancienne_de_meme_cle(tmp_path):
    sortie = tmp_path / "dataset.csv"
    pd.DataFrame([_ligne(1, "2026-06-25", "Soir", 10.0)]).to_csv(sortie, index=False)

    fusion = collect._merge_with_existing(
        pd.DataFrame([_ligne(1, "2026-06-25", "Soir", 20.0)]), sortie
    )

    assert len(fusion) == 1
    assert fusion.iloc[0]["cc_avg"] == 20.0


def test_premier_run_sans_dataset_existant(tmp_path):
    nouveau = pd.DataFrame([_ligne(2, "2026-09-24", "Soir", 93.4)])

    fusion = collect._merge_with_existing(nouveau, tmp_path / "absent.csv")

    assert len(fusion) == 1
