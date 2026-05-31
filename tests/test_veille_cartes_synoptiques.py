"""Tests offline du module cartes_synoptiques.

Couvre :
- Construction d'URL pour Met Office (format ISO ``YYYY-MM-DDTHHMM``)
  et Météociel AROME (format ``YYYYMMDDHH``).
- Robustesse à un fetch HTTP échoué (cartes individuelles → data_uri vide).
- Format de la grille retournée (3 metoffice + 3 arome, labels alignés).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import requests

from apps.veille.cartes_synoptiques import (
    AROME_ECHEANCES,
    LABELS_3,
    METOFFICE_ECHEANCES,
    _url_arome,
    _url_metoffice,
    recuperer_cartes,
)


def test_url_metoffice_format() -> None:
    """L'URL Met Office utilise le format ISO ``YYYY-MM-DDTHHMM``."""
    url = _url_metoffice(date(2026, 5, 31), ech=24)
    assert url == (
        "https://data.consumer-digital.api.metoffice.gov.uk/v1/surface-pressure/"
        "colour/2026-05-31T0000/FSXX00T_24.gif"
    )


def test_url_metoffice_padding_zero() -> None:
    """L'échéance T+0 est paddée à deux chiffres (``_00.gif``, pas ``_0.gif``)."""
    url = _url_metoffice(date(2026, 5, 31), ech=0)
    assert url.endswith("FSXX00T_00.gif")


def test_url_arome_format() -> None:
    """L'URL Météociel utilise le format ``YYYYMMDDHH`` (heure run = 00 UTC)."""
    url = _url_arome(date(2026, 5, 31), ech=24)
    assert url == (
        "https://modeles7.meteociel.fr/modeles/arome/archives/2026053100/arome-24-24-0.png"
    )


def test_recuperer_cartes_grille_complete() -> None:
    """Avec session mockée renvoyant un PNG valide, on obtient 6 cartes encodées."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 255, 255)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    fake_response = MagicMock()
    fake_response.content = png_bytes
    fake_response.raise_for_status = MagicMock()
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    now = pd.Timestamp("2026-05-31 04:15", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=fake_session)

    assert len(grille.metoffice) == 3
    assert len(grille.arome) == 3
    assert grille.run_utc.tz_convert("UTC").strftime("%Y-%m-%d %H:%M") == "2026-05-31 00:00"
    assert grille.nb_disponibles == 6

    # Labels alignés sur les 3 échéances visées.
    assert [c.label for c in grille.metoffice] == list(LABELS_3)
    assert [c.label for c in grille.arome] == list(LABELS_3)

    # Toutes les cartes ont leur data_uri encodée en JPEG.
    for c in grille.metoffice + grille.arome:
        assert c.data_uri.startswith("data:image/jpeg;base64,")


def test_recuperer_cartes_robuste_aux_fetch_echoues() -> None:
    """Si la session lève à chaque get, on récupère 6 cartes à data_uri vide."""
    fake_session = MagicMock()
    fake_session.get.side_effect = requests.ConnectionError("connexion fermée")

    now = pd.Timestamp("2026-05-31 04:15", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=fake_session)

    assert len(grille.metoffice) == 3
    assert len(grille.arome) == 3
    assert grille.nb_disponibles == 0
    assert all(not c.data_uri for c in grille.metoffice + grille.arome)


def test_echeances_metoffice_et_arome_alignees() -> None:
    """Les 2 sources doivent partager le même nombre d'échéances que les labels."""
    assert len(METOFFICE_ECHEANCES) == len(LABELS_3) == 3
    assert len(AROME_ECHEANCES) == len(LABELS_3) == 3
    # AROME démarre à ech=1 car ech=0 n'est pas publié par Météociel.
    assert AROME_ECHEANCES[0] == 1
    # Met Office démarre bien à ech=0 (analyse).
    assert METOFFICE_ECHEANCES[0] == 0
