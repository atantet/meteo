"""Tests des règles de décisions pour l'App 2 Opérationnelle.

Couvre les règles v0+v1 (purge gel, voiles P17, récolte racines,
aération nuit tunnel, fermeture nuit tunnel, déficit plein champ,
demande évap tunnel) sur DataFrames synthétiques + helpers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apps.operationnelle.decisions import (  # noqa: E402
    NIVEAU_ANTICIPER,
    NIVEAU_INFO,
    Carte,
    _saison_active,
    degres_jours_negatifs,
    evaluer_decisions,
    plus_longue_suite_consecutive,
    regle_aeration_nuit_tunnels,
    regle_deficit_plein_champ,
    regle_demande_evap_tunnel,
    regle_fenetre_pluvieuse_travail_sol_ete,
    regle_fenetre_seche_travail_sol_hiver,
    regle_fermeture_nuit_tunnels,
    regle_purge_irrigation_gel,
    regle_recolte_racines_avant_gel,
    regle_voiles_p17,
)

EXPLOITATION_DEFAUT: dict = {
    "saisons": {
        "tunnels_en_culture": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "legumes_racine_au_champ": [10, 11, 12, 1, 2, 3],
        "travail_sol_recherche_fenetre_seche": [11, 12, 1, 2, 3],
        "travail_sol_recherche_fenetre_pluvieuse": [4, 5, 6, 7, 8, 9, 10],
    },
    "equipement": {"voiles_p17_disponibles": True},
    "seuils_gel": {
        "voiles_p17_degres_jours_neg_min": 2.0,
        "recolte_racines_degres_jours_neg_min": 8.0,
    },
    "seuils_tunnel": {
        "aeration_nuit_t_min_celsius": 12.0,
        "aeration_nuit_nuits_min": 2,
        "fermeture_nuit_t_min_celsius": 3.0,
        "fermeture_nuit_nuits_min": 1,
    },
    "seuils_travail_sol": {
        "fenetre_seche_pluie_max_mm_par_jour": 1.0,
        "fenetre_seche_duree_min_jours": 3,
        "fenetre_pluvieuse_pluie_min_mm_par_jour": 5.0,
        "fenetre_pluvieuse_duree_min_jours": 2,
    },
    "seuils_hydrique": {
        "deficit_plein_champ_mm": -10.0,
        "demande_evap_tunnel_etp_cumul_mm": 20.0,
    },
}


def _quotidien(
    t_min: list[float] | None = None,
    t_max: list[float] | None = None,
    pluie: list[float] | None = None,
    etp: list[float] | None = None,
    start: str = "2026-01-01",
) -> pd.DataFrame:
    """Fabrique un DataFrame quotidien minimal pour tester les règles."""
    n = max(len(s) for s in (t_min, t_max, pluie, etp) if s is not None)
    idx = pd.date_range(start, periods=n, freq="D")
    data: dict[str, list[float]] = {}
    if t_min is not None:
        data["t_min_celsius"] = t_min
    if t_max is not None:
        data["t_max_celsius"] = t_max
    if pluie is not None:
        data["pluie_24h_mm"] = pluie
    if etp is not None:
        data["etp_mm"] = etp
    return pd.DataFrame(data, index=idx)


def _texte_complet(c: Carte) -> str:
    """Concatène titre + invitation pour faciliter les assertions."""
    return f"{c.titre} | {c.invitation}".lower()


# ---------- degres_jours_negatifs ----------


def test_dj_neg_serie_vide() -> None:
    assert degres_jours_negatifs(pd.Series([], dtype=float)) == 0.0


def test_dj_neg_tout_positif() -> None:
    assert degres_jours_negatifs(pd.Series([1.0, 5.0, 0.0])) == 0.0


def test_dj_neg_somme_des_valeurs_absolues() -> None:
    assert degres_jours_negatifs(pd.Series([5.0, -3.0, 2.0, -1.0, 0.0])) == 4.0


def test_dj_neg_ignore_zero() -> None:
    assert degres_jours_negatifs(pd.Series([0.0, -2.0])) == 2.0


# ---------- _saison_active ----------


def test_saison_active_dans_fenetre() -> None:
    assert _saison_active({"saisons": {"foo": [3, 4, 5]}}, "foo", 4) is True


def test_saison_active_hors_fenetre() -> None:
    assert _saison_active({"saisons": {"foo": [3, 4, 5]}}, "foo", 8) is False


def test_saison_active_cle_absente_signifie_toujours() -> None:
    assert _saison_active({"saisons": {}}, "foo", 6) is True


def test_saison_active_liste_vide_signifie_toujours() -> None:
    assert _saison_active({"saisons": {"foo": []}}, "foo", 6) is True


# ---------- regle_purge_irrigation_gel ----------


def test_purge_gel_declenchee_quand_t_min_negative() -> None:
    quot = _quotidien(t_min=[5.0, 2.0, -1.0, 3.0])
    carte = regle_purge_irrigation_gel(quot, pd.Timestamp("2026-01-01"))
    assert isinstance(carte, Carte)
    assert carte.niveau == NIVEAU_ANTICIPER
    assert "purger" in _texte_complet(carte)
    # detail_df contient tous les jours (pas seulement le masque).
    assert len(carte.detail_df) == 4
    # surlignage configuré pour T° min ≤ 0.
    assert carte.surlignage == {"t_min_celsius": ("≤", 0.0)}


def test_purge_gel_inactive_sans_gel() -> None:
    quot = _quotidien(t_min=[5.0, 6.0, 7.0])
    assert regle_purge_irrigation_gel(quot, pd.Timestamp("2026-06-01")) is None


# ---------- regle_voiles_p17 (DJ neg) ----------


def test_voiles_declenches_si_dj_neg_au_dessus_seuil() -> None:
    quot = _quotidien(t_min=[5.0, -3.0, 4.0])
    carte = regle_voiles_p17(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-03-15"))
    assert isinstance(carte, Carte)
    txt = _texte_complet(carte)
    assert "p17" in txt
    assert "degrés-jours" in txt
    assert carte.surlignage == {"t_min_celsius": ("<", 0.0)}


def test_voiles_inactifs_si_dj_neg_sous_seuil() -> None:
    quot = _quotidien(t_min=[5.0, -1.0, 4.0])
    assert regle_voiles_p17(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-03-15")) is None


def test_voiles_inactifs_si_voiles_non_disponibles() -> None:
    expl = {**EXPLOITATION_DEFAUT, "equipement": {"voiles_p17_disponibles": False}}
    quot = _quotidien(t_min=[-5.0, -3.0, -2.0])
    assert regle_voiles_p17(quot, expl, pd.Timestamp("2026-01-15")) is None


# ---------- regle_recolte_racines_avant_gel (DJ neg) ----------


def test_racines_declenchees_si_dj_neg_sévère_en_saison() -> None:
    quot = _quotidien(t_min=[0.0, -5.0, -5.0, -3.0])
    carte = regle_recolte_racines_avant_gel(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15"))
    assert isinstance(carte, Carte)
    assert "racine" in _texte_complet(carte)


def test_racines_inactives_hors_fenetre_saisonniere() -> None:
    quot = _quotidien(t_min=[-6.0, -7.0, -8.0])
    assert (
        regle_recolte_racines_avant_gel(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-06-15"))
        is None
    )


def test_racines_inactives_si_gel_modere_seulement() -> None:
    quot = _quotidien(t_min=[-1.0, -1.0, -1.0, -1.0])
    assert (
        regle_recolte_racines_avant_gel(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15"))
        is None
    )


# ---------- regle_aeration_nuit_tunnels ----------


def test_aeration_nuit_declenchee_si_2_nuits_chaudes() -> None:
    quot = _quotidien(t_min=[14.0, 13.0, 10.0, 8.0])
    carte = regle_aeration_nuit_tunnels(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15"))
    assert isinstance(carte, Carte)
    assert carte.niveau == NIVEAU_INFO
    txt = _texte_complet(carte)
    assert "ouvert" in txt or "aér" in txt
    assert carte.surlignage == {"t_min_celsius": ("≥", 12.0)}


def test_aeration_nuit_inactive_si_1_seule_nuit_chaude() -> None:
    quot = _quotidien(t_min=[14.0, 10.0, 8.0])
    assert (
        regle_aeration_nuit_tunnels(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15")) is None
    )


def test_aeration_nuit_inactive_si_toutes_nuits_fraiches() -> None:
    quot = _quotidien(t_min=[8.0, 7.0, 6.0])
    assert (
        regle_aeration_nuit_tunnels(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15")) is None
    )


# ---------- regle_fermeture_nuit_tunnels ----------


def test_fermeture_nuit_declenchee_des_la_premiere_nuit_fraiche() -> None:
    quot = _quotidien(t_min=[2.0, 8.0, 10.0])
    carte = regle_fermeture_nuit_tunnels(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-04-15"))
    assert isinstance(carte, Carte)
    assert "fermer" in _texte_complet(carte)
    assert carte.surlignage == {"t_min_celsius": ("≤", 3.0)}


def test_fermeture_nuit_inactive_si_toutes_nuits_clementes() -> None:
    quot = _quotidien(t_min=[8.0, 10.0, 12.0])
    assert (
        regle_fermeture_nuit_tunnels(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-04-15")) is None
    )


# ---------- regle_deficit_plein_champ ----------


def test_deficit_pc_declenche_si_bilan_cumul_negatif() -> None:
    quot = _quotidien(pluie=[0.0] * 7, etp=[3.0] * 7)
    carte = regle_deficit_plein_champ(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-01"))
    assert isinstance(carte, Carte)
    txt = _texte_complet(carte)
    assert "humidité" in txt or "irrigu" in txt
    # detail_df doit contenir la colonne calculée bilan_eau_jour_mm.
    assert "bilan_eau_jour_mm" in carte.detail_df.columns


def test_deficit_pc_inactif_si_bilan_positif() -> None:
    quot = _quotidien(pluie=[5.0] * 7, etp=[1.0] * 7)
    assert regle_deficit_plein_champ(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-01")) is None


def test_deficit_pc_inactif_si_colonnes_absentes() -> None:
    quot = _quotidien(t_min=[10.0, 11.0, 12.0])
    assert regle_deficit_plein_champ(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-01")) is None


# ---------- plus_longue_suite_consecutive ----------


def test_plus_longue_suite_serie_vide() -> None:
    assert plus_longue_suite_consecutive(pd.Series([], dtype=bool)) is None


def test_plus_longue_suite_aucun_true() -> None:
    assert plus_longue_suite_consecutive(pd.Series([False, False, False])) is None


def test_plus_longue_suite_simple() -> None:
    res = plus_longue_suite_consecutive(pd.Series([False, True, True, True, False]))
    assert res == (1, 3, 3)


def test_plus_longue_suite_choisit_la_plus_longue() -> None:
    # 2 runs : 2 et 4 → on choisit la deuxième.
    res = plus_longue_suite_consecutive(pd.Series([True, True, False, True, True, True, True]))
    assert res == (3, 6, 4)


# ---------- regle_fenetre_seche_travail_sol_hiver ----------


def test_fenetre_seche_declenchee_si_3_jours_secs_en_hiver() -> None:
    # 7 j : pluie 0 sur jours 0-2 (3 jours secs consécutifs), pluie après.
    quot = _quotidien(pluie=[0.0, 0.5, 0.0, 6.0, 8.0, 5.0, 2.0])
    carte = regle_fenetre_seche_travail_sol_hiver(
        quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15")
    )
    assert isinstance(carte, Carte)
    assert carte.niveau == NIVEAU_INFO
    txt = _texte_complet(carte)
    assert "sec" in txt or "sèche" in txt
    assert carte.surlignage == {"pluie_24h_mm": ("≤", 1.0)}


def test_fenetre_seche_inactive_hors_saison_hiver() -> None:
    quot = _quotidien(pluie=[0.0] * 7)
    # Juillet hors fenêtre hiver.
    assert (
        regle_fenetre_seche_travail_sol_hiver(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15"))
        is None
    )


def test_fenetre_seche_inactive_si_jamais_3_jours_secs() -> None:
    # Pluie partout, jamais 3 jours secs consécutifs.
    quot = _quotidien(pluie=[2.0, 0.0, 0.0, 3.0, 0.0, 0.0, 4.0])
    assert (
        regle_fenetre_seche_travail_sol_hiver(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15"))
        is None
    )


# ---------- regle_fenetre_pluvieuse_travail_sol_ete ----------


def test_fenetre_pluvieuse_declenchee_si_2_jours_pluvieux_en_ete() -> None:
    quot = _quotidien(pluie=[0.0, 1.0, 8.0, 10.0, 2.0, 0.0, 0.0])
    carte = regle_fenetre_pluvieuse_travail_sol_ete(
        quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15")
    )
    assert isinstance(carte, Carte)
    assert carte.niveau == NIVEAU_ANTICIPER
    txt = _texte_complet(carte)
    assert "pluvieuse" in txt or "pluie" in txt
    assert carte.surlignage == {"pluie_24h_mm": ("≥", 5.0)}


def test_fenetre_pluvieuse_inactive_hors_saison_ete() -> None:
    quot = _quotidien(pluie=[10.0] * 7)
    # Janvier hors fenêtre été.
    assert (
        regle_fenetre_pluvieuse_travail_sol_ete(
            quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15")
        )
        is None
    )


def test_fenetre_pluvieuse_inactive_si_pluie_modeste() -> None:
    # Pluie faible partout, jamais 2 jours ≥ 5 mm.
    quot = _quotidien(pluie=[2.0, 3.0, 4.0, 1.0, 2.0, 3.0, 0.5])
    assert (
        regle_fenetre_pluvieuse_travail_sol_ete(
            quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15")
        )
        is None
    )


# ---------- regle_demande_evap_tunnel ----------


def test_demande_evap_declenchee_si_etp_cumul_eleve() -> None:
    quot = _quotidien(etp=[4.0] * 7)
    carte = regle_demande_evap_tunnel(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-01"))
    assert isinstance(carte, Carte)
    txt = _texte_complet(carte)
    assert "bassin" in txt or "irrigu" in txt or "stock" in txt


def test_demande_evap_inactive_si_etp_basse() -> None:
    quot = _quotidien(etp=[1.0] * 7)
    assert regle_demande_evap_tunnel(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-01")) is None


# ---------- Source par carte adaptée ----------


def test_carte_purge_gel_source_t_seulement() -> None:
    quot = _quotidien(t_min=[-2.0, 0.0, 5.0])
    carte = regle_purge_irrigation_gel(quot, pd.Timestamp("2026-01-15"))
    assert carte is not None
    # Pas de mention ETP/FAO dans la source d'une carte T° pure.
    assert "etp" not in carte.detail_source.lower()
    assert "fao" not in carte.detail_source.lower()


def test_carte_demande_evap_source_etp() -> None:
    quot = _quotidien(etp=[4.0] * 7)
    carte = regle_demande_evap_tunnel(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-01"))
    assert carte is not None
    assert "fao" in carte.detail_source.lower()


def test_carte_deficit_pc_source_pluie_et_etp() -> None:
    quot = _quotidien(pluie=[0.0] * 7, etp=[3.0] * 7)
    carte = regle_deficit_plein_champ(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-01"))
    assert carte is not None
    assert "pluie" in carte.detail_source.lower()
    assert "fao" in carte.detail_source.lower()


# ---------- evaluer_decisions (orchestration) ----------


def test_evaluer_decisions_hiver_avec_gel_severe_renvoie_cartes_attendues() -> None:
    quot = _quotidien(
        t_min=[-3.0, -6.0, -7.0, -4.0, 0.0, 2.0, 5.0],
        t_max=[5.0, 4.0, 3.0, 8.0, 12.0, 14.0, 16.0],
    )
    cartes = evaluer_decisions(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15"))
    pictos = {c.picto for c in cartes}
    assert "❄️" in pictos, "purge gel manquante"
    assert "🛡️" in pictos, "voiles P17 manquantes"
    assert "🥕" in pictos, "récolte racines manquante"
    assert "🔒" in pictos, "fermeture nuit tunnels manquante"
    assert "🌬️" not in pictos, "aération nuit pas attendue en hiver froid"


def test_evaluer_decisions_ete_chaud_avec_deficit_renvoie_aeration_et_eau() -> None:
    quot = _quotidien(
        t_min=[15.0, 14.0, 16.0, 13.0, 15.0, 14.0, 16.0],
        t_max=[28.0, 30.0, 27.0, 29.0, 31.0, 28.0, 27.0],
        pluie=[0.0] * 7,
        etp=[5.0] * 7,
    )
    cartes = evaluer_decisions(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15"))
    pictos = {c.picto for c in cartes}
    assert "🌬️" in pictos, "aération nuit attendue"
    assert "💧" in pictos, "déficit plein champ attendu"
    assert "🌡️" in pictos, "demande évap tunnel attendue"
    assert "❄️" not in pictos, "pas de gel en été"


def test_evaluer_decisions_printemps_calme_aucune_carte() -> None:
    quot = _quotidien(
        t_min=[8.0, 9.0, 7.0, 8.0, 10.0, 9.0, 8.0],
        t_max=[18.0, 19.0, 17.0, 20.0, 21.0, 19.0, 18.0],
        pluie=[3.0] * 7,
        etp=[2.5] * 7,
    )
    cartes = evaluer_decisions(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-04-15"))
    assert cartes == [], f"Pas de carte attendue, obtenues : {[c.titre for c in cartes]}"


def test_demo_hiver_couvre_5_cartes_attendues() -> None:
    """Le scénario démo hiver doit déclencher purge, voiles, racines, fermeture, sèche."""
    from apps.operationnelle.demo import quotidien_hiver, today_hiver

    exploitation = EXPLOITATION_DEFAUT
    cartes = evaluer_decisions(quotidien_hiver(), exploitation, today_hiver())
    pictos = {c.picto for c in cartes}
    attendus = {"❄️", "🛡️", "🥕", "🔒", "🚜"}
    manquants = attendus - pictos
    assert not manquants, f"Cartes hiver manquantes : {manquants} (obtenu : {pictos})"


def test_demo_ete_couvre_4_cartes_attendues() -> None:
    """Le scénario démo été doit déclencher aération, déficit, évap, pluvieuse."""
    from apps.operationnelle.demo import quotidien_ete, today_ete

    exploitation = EXPLOITATION_DEFAUT
    cartes = evaluer_decisions(quotidien_ete(), exploitation, today_ete())
    pictos = {c.picto for c in cartes}
    attendus = {"🌬️", "💧", "🌡️", "🌧️"}
    manquants = attendus - pictos
    assert not manquants, f"Cartes été manquantes : {manquants} (obtenu : {pictos})"


def test_evaluer_decisions_textes_jamais_imperatif_2pp() -> None:
    """Garantit le principe : on invite, on ne tranche pas. Vérifie titre + invitation."""
    quot = _quotidien(
        t_min=[-6.0, -7.0, -3.0, 0.0, 5.0, 12.0, 15.0],
        t_max=[2.0, 1.0, 5.0, 8.0, 14.0, 22.0, 25.0],
        pluie=[0.0] * 7,
        etp=[4.0] * 7,
    )
    cartes = evaluer_decisions(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15"))
    assert len(cartes) > 0
    # Impératif 2e personne pluriel = ton "prescriptif". L'infinitif
    # ("penser à fermer") reste OK (mode invitation).
    bannis_2pp = [
        "il faut",
        "vous devez",
        "irriguez",
        "couvrez",
        "récoltez",
        "fermez",
        "ouvrez",
        "aérez",
        "purgez",
    ]
    for c in cartes:
        texte = _texte_complet(c)
        for mot in bannis_2pp:
            assert mot not in texte, (
                f"Ton impératif détecté : « {c.titre} | {c.invitation} » (mot : {mot})"
            )
