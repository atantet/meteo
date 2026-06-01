"""Tests des règles de guides de décision pour l'App 2 Opérationnelle.

Couvre les règles (froid, tunnels, hydrique, thermique, travail sol) sur
DataFrames synthétiques + helpers. Un guide peut être *actif* (signal
franchi) ou *inactif* (signal sous seuil) ; hors saison la règle renvoie
toujours ``None`` (guide non applicable).
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
    THEME_FROID,
    THEME_IRRIGATION,
    THEME_TRAVAIL_SOL,
    THEME_TUNNEL,
    GuideDecision,
    _saison_active,
    degres_jours_sous_seuil,
    evaluer_decisions,
    get_chemin,
    grouper_par_theme,
    plus_longue_suite_consecutive,
    regle_aeration_nuit_tunnels,
    regle_deficit_hydrique,
    regle_fenetre_pluvieuse_travail_sol_ete,
    regle_fenetre_seche_travail_sol_hiver,
    regle_fermeture_nuit_tunnels,
    regle_purge_irrigation_gel,
    regle_recolte_racines_avant_gel,
    regle_stress_thermique,
    regle_voiles_p17,
    set_chemin,
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
        "purge_irrigation_t_seuil_celsius": 0.0,
        "voiles_p17_t_seuil_celsius": 0.0,
        "voiles_p17_degres_jours_min": 2.0,
        "recolte_racines_t_seuil_celsius": -5.0,
        "recolte_racines_degres_jours_min": 4.0,
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
        "deficit_mm": -10.0,
    },
    "seuils_thermique": {
        "stress_t_max_celsius": 28.0,
        "stress_jours_min": 2,
    },
}


def _quotidien(
    t_min: list[float] | None = None,
    t_max: list[float] | None = None,
    pluie: list[float] | None = None,
    etp: list[float] | None = None,
    start: str = "2026-01-01",
) -> pd.DataFrame:
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


# ---------- get_chemin / set_chemin ----------


def test_get_chemin_simple() -> None:
    assert get_chemin({"a": {"b": 1}}, "a.b") == 1


def test_set_chemin_existant() -> None:
    d = {"a": {"b": 1}}
    set_chemin(d, "a.b", 42)
    assert d == {"a": {"b": 42}}


def test_set_chemin_cree_les_niveaux() -> None:
    d: dict = {}
    set_chemin(d, "a.b.c", 7)
    assert d == {"a": {"b": {"c": 7}}}


# ---------- degres_jours_sous_seuil ----------


def test_dj_serie_vide() -> None:
    assert degres_jours_sous_seuil(pd.Series([], dtype=float), 0.0) == 0.0


def test_dj_seuil_0_equivalent_ancien_dj_neg() -> None:
    assert degres_jours_sous_seuil(pd.Series([5.0, -3.0, 2.0, -1.0, 0.0]), 0.0) == 4.0


def test_dj_seuil_severe_minus_5() -> None:
    assert degres_jours_sous_seuil(pd.Series([0.0, -7.0, -8.0, -4.0]), -5.0) == 5.0


# ---------- _saison_active ----------


def test_saison_active_dans_fenetre() -> None:
    assert _saison_active({"saisons": {"foo": [3, 4, 5]}}, "foo", 4) is True


def test_saison_active_hors_fenetre() -> None:
    assert _saison_active({"saisons": {"foo": [3, 4, 5]}}, "foo", 8) is False


def test_saison_active_cle_absente_signifie_toujours() -> None:
    assert _saison_active({"saisons": {}}, "foo", 6) is True


# ---------- regle_purge_irrigation_gel : active / inactive ----------


def test_purge_gel_active_quand_t_min_negative() -> None:
    quot = _quotidien(t_min=[5.0, 2.0, -1.0, 3.0])
    guide = regle_purge_irrigation_gel(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-01"))
    assert isinstance(guide, GuideDecision)
    assert guide.active is True
    assert guide.niveau == NIVEAU_ANTICIPER
    assert "purger" in guide.titre.lower()
    assert guide.surlignage == {"t_min_celsius": ("≤", 0.0)}


def test_purge_gel_inactive_sans_gel() -> None:
    """Désormais la guide est rendue grisée plutôt que None."""
    quot = _quotidien(t_min=[5.0, 6.0, 7.0])
    guide = regle_purge_irrigation_gel(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-06-01"))
    assert isinstance(guide, GuideDecision)
    assert guide.active is False
    assert "pas de gel" in guide.titre.lower()
    # Paramètres ajustables toujours présents pour modifier les seuils.
    assert any(
        p.chemin == "seuils_gel.purge_irrigation_t_seuil_celsius"
        for p in guide.parametres_ajustables
    )


def test_purge_gel_seuil_relevable_pour_anticiper() -> None:
    expl = {**EXPLOITATION_DEFAUT}
    expl["seuils_gel"] = {**expl["seuils_gel"], "purge_irrigation_t_seuil_celsius": 2.0}
    quot = _quotidien(t_min=[5.0, 1.5, 4.0])
    guide = regle_purge_irrigation_gel(quot, expl, pd.Timestamp("2026-01-15"))
    assert guide is not None and guide.active is True
    assert guide.surlignage == {"t_min_celsius": ("≤", 2.0)}


# ---------- regle_voiles_p17 ----------


def test_voiles_active_si_dj_au_dessus_seuil() -> None:
    quot = _quotidien(t_min=[5.0, -3.0, 4.0])
    guide = regle_voiles_p17(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-03-15"))
    assert guide is not None and guide.active is True
    assert "p17" in guide.titre.lower()


def test_voiles_inactive_si_dj_sous_seuil() -> None:
    quot = _quotidien(t_min=[5.0, -1.0, 4.0])
    guide = regle_voiles_p17(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-03-15"))
    assert guide is not None and guide.active is False


def test_voiles_filtree_si_voiles_non_disponibles() -> None:
    """Pas d'équipement → on cache la guide (None)."""
    expl = {**EXPLOITATION_DEFAUT, "equipement": {"voiles_p17_disponibles": False}}
    quot = _quotidien(t_min=[-5.0, -3.0, -2.0])
    assert regle_voiles_p17(quot, expl, pd.Timestamp("2026-01-15")) is None


# ---------- regle_recolte_racines (saison + active/inactive) ----------


def test_racines_active_si_dj_severe_en_saison() -> None:
    quot = _quotidien(t_min=[0.0, -7.0, -8.0, -3.0])
    guide = regle_recolte_racines_avant_gel(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15"))
    assert guide is not None and guide.active is True


def test_racines_inactive_en_saison_sans_gel_severe() -> None:
    quot = _quotidien(t_min=[-4.0, -4.0, -4.0])
    guide = regle_recolte_racines_avant_gel(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15"))
    assert guide is not None and guide.active is False


def test_racines_filtree_hors_saison() -> None:
    quot = _quotidien(t_min=[-7.0, -8.0, -6.0])
    assert (
        regle_recolte_racines_avant_gel(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-06-15"))
        is None
    )


# ---------- regle_aeration_nuit_tunnels ----------


def test_aeration_active_si_2_nuits_chaudes() -> None:
    quot = _quotidien(t_min=[14.0, 13.0, 10.0, 8.0])
    guide = regle_aeration_nuit_tunnels(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15"))
    assert guide is not None and guide.active is True
    assert guide.niveau == NIVEAU_INFO


def test_aeration_inactive_si_pas_assez_de_nuits_chaudes() -> None:
    quot = _quotidien(t_min=[14.0, 10.0, 8.0])
    guide = regle_aeration_nuit_tunnels(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15"))
    assert guide is not None and guide.active is False


# ---------- regle_fermeture_nuit_tunnels ----------


def test_fermeture_active_des_la_premiere_nuit_fraiche() -> None:
    quot = _quotidien(t_min=[2.0, 8.0, 10.0])
    guide = regle_fermeture_nuit_tunnels(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-04-15"))
    assert guide is not None and guide.active is True


def test_fermeture_inactive_si_toutes_nuits_clementes() -> None:
    quot = _quotidien(t_min=[8.0, 10.0, 12.0])
    guide = regle_fermeture_nuit_tunnels(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-04-15"))
    assert guide is not None and guide.active is False


# ---------- plus_longue_suite_consecutive ----------


def test_plus_longue_suite_serie_vide() -> None:
    assert plus_longue_suite_consecutive(pd.Series([], dtype=bool)) is None


def test_plus_longue_suite_simple() -> None:
    assert plus_longue_suite_consecutive(pd.Series([False, True, True, True, False])) == (
        1,
        3,
        3,
    )


def test_plus_longue_suite_choisit_la_plus_longue() -> None:
    assert plus_longue_suite_consecutive(
        pd.Series([True, True, False, True, True, True, True])
    ) == (3, 6, 4)


# ---------- regle_fenetre_seche_travail_sol_hiver ----------


def test_fenetre_seche_active_si_3_jours_secs() -> None:
    quot = _quotidien(pluie=[0.0, 0.5, 0.0, 6.0, 8.0, 5.0, 2.0])
    guide = regle_fenetre_seche_travail_sol_hiver(
        quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15")
    )
    assert guide is not None and guide.active is True


def test_fenetre_seche_inactive_si_jamais_3_jours_secs_en_saison() -> None:
    quot = _quotidien(pluie=[2.0, 0.0, 3.0, 0.0, 4.0])
    guide = regle_fenetre_seche_travail_sol_hiver(
        quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15")
    )
    assert guide is not None and guide.active is False


def test_fenetre_seche_filtree_hors_saison_hiver() -> None:
    quot = _quotidien(pluie=[0.0] * 7)
    assert (
        regle_fenetre_seche_travail_sol_hiver(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15"))
        is None
    )


# ---------- regle_fenetre_pluvieuse_travail_sol_ete ----------


def test_fenetre_pluvieuse_active_si_2_jours_pluvieux() -> None:
    quot = _quotidien(pluie=[0.0, 1.0, 8.0, 10.0, 2.0, 0.0, 0.0])
    guide = regle_fenetre_pluvieuse_travail_sol_ete(
        quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15")
    )
    assert guide is not None and guide.active is True


def test_fenetre_pluvieuse_titre_sans_avant_quand_active() -> None:
    quot = _quotidien(pluie=[8.0, 10.0, 12.0])
    guide = regle_fenetre_pluvieuse_travail_sol_ete(
        quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-15")
    )
    assert guide is not None and guide.active is True
    assert "avant" not in guide.titre


# ---------- regle_deficit_hydrique ----------


def test_deficit_active_si_bilan_negatif() -> None:
    quot = _quotidien(pluie=[0.0] * 7, etp=[3.0] * 7)
    guide = regle_deficit_hydrique(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-01"))
    assert guide is not None and guide.active is True


def test_deficit_inactive_si_bilan_positif() -> None:
    quot = _quotidien(pluie=[5.0] * 7, etp=[1.0] * 7)
    guide = regle_deficit_hydrique(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-01"))
    assert guide is not None and guide.active is False


# ---------- regle_stress_thermique ----------


def test_stress_thermique_active_si_3_jours_chauds() -> None:
    quot = _quotidien(t_max=[25.0, 30.0, 32.0, 28.5, 22.0])
    guide = regle_stress_thermique(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-01"))
    assert guide is not None and guide.active is True


def test_stress_thermique_inactive_si_1_seul_jour() -> None:
    quot = _quotidien(t_max=[30.0, 22.0, 20.0])
    guide = regle_stress_thermique(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-07-01"))
    assert guide is not None and guide.active is False


# ---------- Démo (toutes règles applicables s'affichent, active=True attendu) ----------


def test_demo_hiver_a_les_guides_actifs_attendus() -> None:
    from apps.operationnelle.demo import quotidien_hiver, today_hiver

    guides = evaluer_decisions(quotidien_hiver(), EXPLOITATION_DEFAUT, today_hiver())
    pictos_actifs = {g.picto for g in guides if g.active}
    attendus = {"❄️", "🛡️", "🥕", "🔒", "🚜"}
    assert attendus.issubset(pictos_actifs), (
        f"Guides hiver actifs manquants : {attendus - pictos_actifs}"
    )


def test_demo_ete_a_les_guides_actifs_attendus() -> None:
    from apps.operationnelle.demo import quotidien_ete, today_ete

    guides = evaluer_decisions(quotidien_ete(), EXPLOITATION_DEFAUT, today_ete())
    pictos_actifs = {g.picto for g in guides if g.active}
    attendus = {"🌬️", "💧", "🌡️", "🌧️"}
    assert attendus.issubset(pictos_actifs), (
        f"Guides été actifs manquants : {attendus - pictos_actifs}"
    )


# ---------- Orchestration : titres jamais en mode impératif ----------


def test_titres_jamais_imperatif_2pp() -> None:
    quot = _quotidien(
        t_min=[-6.0, -7.0, -3.0, 0.0, 5.0, 12.0, 15.0],
        t_max=[2.0, 1.0, 5.0, 8.0, 14.0, 22.0, 25.0],
        pluie=[0.0] * 7,
        etp=[4.0] * 7,
    )
    guides = evaluer_decisions(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15"))
    assert len(guides) > 0
    bannis = [
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
    for g in guides:
        t = g.titre.lower()
        for mot in bannis:
            assert mot not in t, f"Ton impératif détecté : « {g.titre} »"


# ---------- Regroupement par thème ----------


def test_chaque_regle_a_un_theme_valide() -> None:
    """Tout guide retourné par les règles porte un thème dans `THEMES_ORDRE`."""
    quot = _quotidien(
        t_min=[-6.0, -7.0, -3.0, 0.0, 5.0, 12.0, 15.0],
        t_max=[30.0, 31.0, 25.0, 18.0, 14.0, 22.0, 25.0],
        pluie=[0.0] * 7,
        etp=[4.0] * 7,
    )
    guides = evaluer_decisions(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15"))
    themes_valides = {THEME_FROID, THEME_TUNNEL, THEME_IRRIGATION, THEME_TRAVAIL_SOL}
    for g in guides:
        assert g.theme in themes_valides, f"Thème inconnu : « {g.theme} » pour « {g.titre} »"


def test_grouper_par_theme_respecte_ordre() -> None:
    """`grouper_par_theme` renvoie les thèmes dans l'ordre canonique."""
    quot = _quotidien(
        t_min=[-6.0, -7.0, -3.0, 0.0, 5.0, 12.0, 15.0],
        t_max=[30.0, 31.0, 25.0, 18.0, 14.0, 22.0, 25.0],
        pluie=[0.0] * 7,
        etp=[4.0] * 7,
    )
    guides = evaluer_decisions(quot, EXPLOITATION_DEFAUT, pd.Timestamp("2026-01-15"))
    groupes = grouper_par_theme(guides)
    themes = [t for t, _ in groupes]
    # L'ordre dans la liste retournée doit être : froid puis tunnel
    # puis irrigation puis travail_sol (l'ordre canonique de THEMES_ORDRE),
    # même si certains thèmes sont absents.
    ordre_canonique = [THEME_FROID, THEME_TUNNEL, THEME_IRRIGATION, THEME_TRAVAIL_SOL]
    positions = [ordre_canonique.index(t) for t in themes]
    assert positions == sorted(positions), f"Ordre des thèmes incorrect : {themes}"
