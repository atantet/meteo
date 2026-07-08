"""Tests offline du module `apps.operationnelle.cartes_geo`.

Couvre :

- Construction d'URL pour Météociel ARPEGE-Europe mode 7 (résumé) et ECMWF
  0.25° mode 36.
- Choix du run : multiple de 6 h le plus récent, avec latence publication de
  5 h (ARPEGE-Europe) ou 7 h 15 (ECMWF).
- Robustesse à un fetch HTTP échoué (cartes individuelles → data_uri vide).
- Format de la série retournée (4 cartes).
- Cibles correctement calculées (run + ech).
- Run déterministe sans fallback : une carte 404 reste vide (ADR-0011 D4).
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pandas as pd
import requests

from apps.operationnelle.cartes_geo import (
    ARPEGE_EUR_ECHEANCES,
    _run_le_plus_recent,
    _run_le_plus_recent_ecmwf,
    _url_arpege_eur,
    _url_ecmwf,
    lien_ecmwf_ctrl,
    recuperer_cartes,
    recuperer_cartes_ecmwf,
)


def test_url_arpege_eur_format() -> None:
    """L'URL Météociel encode le run UTC en YYYYMMDDHH et le mode 7."""
    run = pd.Timestamp("2026-06-01 12:00", tz="UTC")
    url = _url_arpege_eur(run, ech=48)
    assert url == "https://modeles7.meteociel.fr/modeles/arpege/run/2026060112/arpegeeur-7-48.png"


def test_echeances_attendues() -> None:
    """ARPEGE-Europe Météociel résumé : 4 cibles J+1 / J+2 / J+3 / J+4."""
    assert ARPEGE_EUR_ECHEANCES == (24, 48, 72, 96)


def test_run_le_plus_recent_arrondit_au_cycle_6h() -> None:
    """now=12 UTC → run 06 UTC (12 - 5 = 7 UTC → floor 6 h = 6 UTC)."""
    now = pd.Timestamp("2026-06-01 12:00", tz="UTC")
    assert _run_le_plus_recent(now) == pd.Timestamp("2026-06-01 06:00", tz="UTC")


def test_run_le_plus_recent_bascule_jour_precedent() -> None:
    """now=02 UTC → 21 UTC veille → floor 6 h = 18 UTC veille."""
    now = pd.Timestamp("2026-06-01 02:00", tz="UTC")
    assert _run_le_plus_recent(now) == pd.Timestamp("2026-05-31 18:00", tz="UTC")


def _fake_session_succes() -> MagicMock:
    """Session mockée qui retourne un PNG 8×8 valide pour tout get."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 255, 255)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    fake_response = MagicMock()
    fake_response.content = png_bytes
    fake_response.raise_for_status = MagicMock()
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    return fake_session


def test_recuperer_cartes_utilise_run_le_plus_recent() -> None:
    """Le run choisi est celui que `_run_le_plus_recent` calcule."""
    now = pd.Timestamp("2026-06-01 12:00", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=_fake_session_succes())

    run_attendu = _run_le_plus_recent(now)
    assert len(grille.cartes) == 4
    assert grille.nb_disponibles == 4
    for c in grille.cartes:
        assert c.run_utc == run_attendu
        assert c.data_uri.startswith("data:image/jpeg;base64,")


def test_recuperer_cartes_cibles_coherentes() -> None:
    """Pour chaque carte, ``cible_utc`` = ``run_utc + ech`` heures."""
    now = pd.Timestamp("2026-06-01 12:00", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=_fake_session_succes())

    for c in grille.cartes:
        attendu = c.run_utc + pd.Timedelta(hours=c.echeance_h)
        assert c.cible_utc == attendu


def test_recuperer_cartes_robuste_aux_fetch_echoues() -> None:
    """Si la session lève à chaque get, on récupère 4 cartes data_uri vide."""
    fake_session = MagicMock()
    fake_session.get.side_effect = requests.ConnectionError("connexion fermée")

    now = pd.Timestamp("2026-06-01 12:00", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=fake_session)

    assert len(grille.cartes) == 4
    assert grille.nb_disponibles == 0
    assert all(not c.data_uri for c in grille.cartes)


def test_recuperer_cartes_run_deterministe_sans_fallback() -> None:
    """404 sur une carte → run inchangé (déterministe, ADR-0011 D4), carte vide.

    Plus de bascule sur le run précédent : la carte en échec reste vide, les
    autres du même run sont servies.
    """
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 255, 255)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    fake_response_ok = MagicMock()
    fake_response_ok.content = png_bytes
    fake_response_ok.raise_for_status = MagicMock()
    fake_session = MagicMock()
    # 1ʳᵉ carte : 404 ; les 3 autres : OK. Aucun appel de fallback.
    fake_session.get.side_effect = [
        requests.HTTPError("404"),
        fake_response_ok,
        fake_response_ok,
        fake_response_ok,
    ]

    now = pd.Timestamp("2026-06-01 12:00", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=fake_session)

    run_courant = _run_le_plus_recent(now)
    # Toutes les cartes restent sur le run déterministe (aucun repli).
    for c in grille.cartes:
        assert c.run_utc == run_courant
    # La 1ʳᵉ (404) est vide ; les 3 autres sont disponibles.
    assert not grille.cartes[0].data_uri
    assert grille.nb_disponibles == 3
    # Exactement 4 fetchs (1 par échéance), pas 5 → pas de fallback.
    assert fake_session.get.call_count == 4


# --------------------------------------------------------------------------
# ECMWF (mêmes garanties que ARPEGE-Europe, latence de publication propre).
# --------------------------------------------------------------------------


def test_url_ecmwf_format() -> None:
    """URL Météociel confirmée en direct : modeles3/.../ecmwf2/runs/<run>/ecmwf-36-<ech>.png."""
    run = pd.Timestamp("2026-07-08 00:00", tz="UTC")
    url = _url_ecmwf(run, ech=72)
    assert url == "https://modeles3.meteociel.fr/modeles/ecmwf2/runs/2026070800/ecmwf-36-72.png?0"


def test_lien_ecmwf_ctrl_adapte_echeance() -> None:
    """Le lien humain vers ecmwf_ctrl.php porte l'échéance de la carte concernée."""
    assert (
        lien_ecmwf_ctrl(72)
        == "https://www.meteociel.fr/modeles/ecmwf_ctrl.php?ech=72&mode=36&carte=0&"
    )


def test_run_le_plus_recent_ecmwf_latence_7h15() -> None:
    """now=08 UTC → run 00 UTC (08 - 7.25 = 00.75 UTC → floor 6 h = 00 UTC)."""
    now = pd.Timestamp("2026-07-08 08:00", tz="UTC")
    assert _run_le_plus_recent_ecmwf(now) == pd.Timestamp("2026-07-08 00:00", tz="UTC")


def test_run_le_plus_recent_ecmwf_latence_plus_longue_qu_arpege() -> None:
    """now=12 UTC : ARPEGE prend déjà le run 06Z (latence 5 h) alors qu'ECMWF
    reste sur le run 00Z (latence 7 h 15 : 12 - 7.25 = 4.75 UTC → floor 00 UTC).
    """
    now = pd.Timestamp("2026-07-08 12:00", tz="UTC")
    assert _run_le_plus_recent_ecmwf(now) == pd.Timestamp("2026-07-08 00:00", tz="UTC")
    assert _run_le_plus_recent(now) == pd.Timestamp("2026-07-08 06:00", tz="UTC")


def test_recuperer_cartes_ecmwf_utilise_run_le_plus_recent_ecmwf() -> None:
    """Le run choisi pour ECMWF suit sa propre latence (7 h 15), pas celle d'ARPEGE."""
    now = pd.Timestamp("2026-07-08 12:00", tz="UTC")
    cibles = (
        pd.Timestamp("2026-07-11 06:00", tz="UTC"),
        pd.Timestamp("2026-07-12 06:00", tz="UTC"),
    )
    grille = recuperer_cartes_ecmwf(cibles, now_utc=now, session=_fake_session_succes())

    run_attendu = _run_le_plus_recent_ecmwf(now)
    assert run_attendu != _run_le_plus_recent(now)  # latences différentes → runs différents ici
    assert len(grille.cartes) == 2
    assert grille.nb_disponibles == 2
    for c, cible in zip(grille.cartes, cibles, strict=True):
        assert c.run_utc == run_attendu
        assert c.cible_utc == cible  # cible UTC exacte demandée, pas run+72/96 fixe
        assert c.data_uri.startswith("data:image/jpeg;base64,")


def test_recuperer_cartes_ecmwf_cible_pas_echeance_fixe() -> None:
    """Bug corrigé : ECMWF doit viser les mêmes cibles UTC qu'ARPEGE, pas +72/+96 h
    depuis son propre run (qui décale le jour calendaire affiché — cf. retour terrain).
    """
    now = pd.Timestamp("2026-07-08 05:30", tz="UTC")
    run_arpege = _run_le_plus_recent(now)
    run_ecmwf = _run_le_plus_recent_ecmwf(now)
    assert run_arpege != run_ecmwf, "test non pertinent si les runs coïncident"

    cible_arpege = run_arpege + pd.Timedelta(hours=72)
    grille = recuperer_cartes_ecmwf((cible_arpege,), now_utc=now, session=_fake_session_succes())

    assert grille.cartes[0].cible_utc == cible_arpege
    # L'échéance ECMWF affichée n'est PAS 72 h (run différent) — c'est attendu.
    assert grille.cartes[0].echeance_h == int((cible_arpege - run_ecmwf).total_seconds() // 3600)


def test_recuperer_cartes_ecmwf_robuste_aux_fetch_echoues() -> None:
    """Si la session lève à chaque get, les cartes ECMWF restent vides (jamais de fausse valeur)."""
    fake_session = MagicMock()
    fake_session.get.side_effect = requests.ConnectionError("connexion fermée")

    now = pd.Timestamp("2026-07-08 12:00", tz="UTC")
    cibles = (
        pd.Timestamp("2026-07-11 06:00", tz="UTC"),
        pd.Timestamp("2026-07-12 06:00", tz="UTC"),
    )
    grille = recuperer_cartes_ecmwf(cibles, now_utc=now, session=fake_session)

    assert len(grille.cartes) == 2
    assert grille.nb_disponibles == 0
    assert all(not c.data_uri for c in grille.cartes)
    assert all(c.motif_indispo for c in grille.cartes)
