"""Tests offline du module cartes_synoptiques.

Couvre :

- Construction d'URL pour Met Office (format ISO ``YYYY-MM-DDTHHMM``)
  et Météociel AROME (format ``YYYYMMDDHH`` pour un run quelconque).
- Choix des runs : Met Office = 00 UTC jour ; AROME = 18 UTC veille
  (run 00 UTC pas dispo avant ~08 UTC sur Météociel).
- Robustesse à un fetch HTTP échoué (cartes individuelles → data_uri vide).
- Format de la grille retournée (3 metoffice + 3 arome).
- Cibles correctement calculées (run + ech).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import requests

from apps.veille.cartes_synoptiques import (
    AROME_ECHEANCES,
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


def test_url_arome_format_run_18z() -> None:
    """L'URL Météociel encode l'heure du run (18Z veille pour AROME)."""
    run = pd.Timestamp("2026-05-31 18:00", tz="UTC")
    url = _url_arome(run, ech=6)
    assert url == (
        "https://modeles7.meteociel.fr/modeles/arome/archives/2026053118/arome-24-6-0.png"
    )


def test_recuperer_cartes_choisit_runs_distincts() -> None:
    """Met Office utilise 00 UTC du jour, AROME utilise 18 UTC de la veille."""
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

    now = pd.Timestamp("2026-06-01 05:30", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=fake_session)

    assert len(grille.metoffice) == 4
    assert len(grille.arome) == 4
    assert grille.nb_disponibles == 8

    # Met Office : run 00 UTC du jour courant.
    for c in grille.metoffice:
        assert c.run_utc == pd.Timestamp("2026-06-01 00:00", tz="UTC")

    # AROME : run 18 UTC de la veille.
    for c in grille.arome:
        assert c.run_utc == pd.Timestamp("2026-05-31 18:00", tz="UTC")

    # Toutes les cartes ont leur data_uri encodée en JPEG.
    for c in grille.metoffice + grille.arome:
        assert c.data_uri.startswith("data:image/jpeg;base64,")


def test_recuperer_cartes_cibles_synchrones_entre_sources() -> None:
    """Les 4 cibles UTC sont identiques entre MetOffice et AROME."""
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

    now = pd.Timestamp("2026-06-01 05:30", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=fake_session)

    cibles_attendues = [
        pd.Timestamp("2026-06-01 00:00", tz="UTC"),  # 00 UTC J
        pd.Timestamp("2026-06-01 12:00", tz="UTC"),  # 12 UTC J
        pd.Timestamp("2026-06-02 00:00", tz="UTC"),  # 00 UTC J+1
        pd.Timestamp("2026-06-02 12:00", tz="UTC"),  # 12 UTC J+1
    ]
    assert [c.cible_utc for c in grille.metoffice] == cibles_attendues
    assert [c.cible_utc for c in grille.arome] == cibles_attendues


def test_recuperer_cartes_robuste_aux_fetch_echoues() -> None:
    """Si la session lève à chaque get, on récupère 6 cartes à data_uri vide."""
    fake_session = MagicMock()
    fake_session.get.side_effect = requests.ConnectionError("connexion fermée")

    now = pd.Timestamp("2026-06-01 05:30", tz="UTC")
    grille = recuperer_cartes(now_utc=now, session=fake_session)

    assert len(grille.metoffice) == 4
    assert len(grille.arome) == 4
    assert grille.nb_disponibles == 0
    assert all(not c.data_uri for c in grille.metoffice + grille.arome)


def test_echeances_metoffice_et_arome_synchrones() -> None:
    """Les 2 séries pointent sur les mêmes cibles : décalage AROME = MetOffice + 6 h."""
    assert METOFFICE_ECHEANCES == (0, 12, 24, 36)
    assert AROME_ECHEANCES == (6, 18, 30, 42)
    # Synchro : run AROME 18Z veille + ech_arome = run MetOffice 00Z jour + ech_metoffice.
    # 18 - 24 + ech_arome = 0 + ech_metoffice  →  ech_arome - 6 = ech_metoffice.
    for ech_metoffice, ech_arome in zip(METOFFICE_ECHEANCES, AROME_ECHEANCES, strict=True):
        assert ech_arome - 6 == ech_metoffice
