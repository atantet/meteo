"""Tests offline du module `apps.operationnelle.cartes_geo`.

Couvre :

- Construction d'URL pour Météociel ECMWF (format ``YYYYMMDDHH`` + ECM<M>-<ech>.GIF).
- Choix du run : 00 UTC du jour si ``now`` ≥ 08 UTC, sinon 00 UTC veille.
- Robustesse à un fetch HTTP échoué (cartes individuelles → data_uri vide).
- Format de la série retournée (4 cartes ECMWF).
- Cibles correctement calculées (run + ech).
- Fallback automatique vers la veille si la 1ʳᵉ carte du run du jour 404.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pandas as pd
import requests

from apps.operationnelle.cartes_geo import (
    ECMWF_ECHEANCES,
    _url_ecmwf,
    recuperer_cartes,
)


def test_url_ecmwf_format_run_00z() -> None:
    """L'URL Météociel encode le run UTC en YYYYMMDDHH."""
    run = pd.Timestamp("2026-06-01 00:00", tz="UTC")
    url = _url_ecmwf(run, ech=48)
    assert url == "https://www.meteociel.fr/modeles/ecmwf/runs/2026060100/ECM0-48.GIF"


def test_url_ecmwf_echeances_attendues() -> None:
    """ECMWF Météociel : 4 cibles J+0 / J+2 / J+4 / J+6 en T+0/48/96/144 h."""
    assert ECMWF_ECHEANCES == (0, 48, 96, 144)


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


def test_recuperer_cartes_choisit_run_jour_apres_08utc() -> None:
    """À 10 UTC, le run 00 UTC du jour courant est dispo : on l'utilise."""
    now = pd.Timestamp("2026-06-01 10:00", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=_fake_session_succes())

    assert len(grille.cartes) == 4
    assert grille.nb_disponibles == 4
    for c in grille.cartes:
        assert c.run_utc == pd.Timestamp("2026-06-01 00:00", tz="UTC")
        assert c.data_uri.startswith("data:image/jpeg;base64,")


def test_recuperer_cartes_choisit_run_veille_avant_08utc() -> None:
    """À 05 UTC, le run 00 UTC du jour n'est pas encore publié : on prend la veille."""
    now = pd.Timestamp("2026-06-01 05:00", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=_fake_session_succes())

    for c in grille.cartes:
        assert c.run_utc == pd.Timestamp("2026-05-31 00:00", tz="UTC")


def test_recuperer_cartes_cibles_cohérentes_avec_run() -> None:
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


def test_recuperer_cartes_fallback_veille_si_premiere_carte_jour_echoue() -> None:
    """Si la 1ʳᵉ carte du run du jour 404, on bascule sur le run de la veille."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 255, 255)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    # 1ère réponse : exception (run du jour échoue), suivantes : succès.
    fake_response_ok = MagicMock()
    fake_response_ok.content = png_bytes
    fake_response_ok.raise_for_status = MagicMock()
    fake_session = MagicMock()
    fake_session.get.side_effect = [
        requests.HTTPError("404"),
        fake_response_ok,
        fake_response_ok,
        fake_response_ok,
        fake_response_ok,
    ]

    now = pd.Timestamp("2026-06-01 12:00", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=fake_session)

    # Toutes les cartes doivent pointer sur le run de la veille.
    for c in grille.cartes:
        assert c.run_utc == pd.Timestamp("2026-05-31 00:00", tz="UTC")
    # Les 4 cartes du fallback sont OK.
    assert grille.nb_disponibles == 4
