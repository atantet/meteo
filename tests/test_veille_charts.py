"""Tests `apps.veille.charts` — génération graphique 72 h."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _prevision_synth() -> pd.DataFrame:
    index = pd.date_range("2024-06-15 00:00:00+00:00", periods=168, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": np.linspace(285, 295, 168),
            "humidite_relative": np.full(168, 0.7),
            "precipitation": np.full(168, 0.1),
            "probabilite_pluie_pct": np.full(168, 30.0),
            "vitesse_vent_10m": np.full(168, 5.0),
            "rafales_vent_10m": np.full(168, 9.0),
            "rayonnement_global": np.full(168, 100000.0),
        },
        index=index,
    )


def test_graphique_72h_base64_prefixe_data_uri() -> None:
    from apps.veille.charts import graphique_72h_base64

    prevision = _prevision_synth()
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    data_uri = graphique_72h_base64(prevision, now)
    assert data_uri.startswith("data:image/png;base64,")
    # Base64 PNG non vide.
    assert len(data_uri) > 1000


def test_graphique_72h_base64_prevision_vide() -> None:
    """now_utc dans le futur lointain → DataFrame vide → chaîne vide."""
    from apps.veille.charts import graphique_72h_base64

    prevision = _prevision_synth()
    now = pd.Timestamp("2030-01-01 00:00:00+00:00")
    assert graphique_72h_base64(prevision, now) == ""


def test_graphique_72h_pas_de_proba_si_colonne_absente() -> None:
    """Robuste à l'absence de probabilite_pluie_pct."""
    from apps.veille.charts import graphique_72h_base64

    prev = _prevision_synth().drop(columns=["probabilite_pluie_pct"])
    now = pd.Timestamp("2024-06-15 00:00:00+00:00")
    data_uri = graphique_72h_base64(prev, now)
    assert data_uri.startswith("data:image/png;base64,")


# ---------- Carte synoptique DWD ----------


def _png_de_test(width: int = 1000, height: int = 600) -> bytes:
    """Petit PNG synthétique pour mocker DWD."""
    import io as _io

    from PIL import Image

    img = Image.new("RGB", (width, height), (200, 220, 255))
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_carte_synoptique_redimensionne_et_encode() -> None:
    from unittest.mock import MagicMock

    from apps.veille.charts import carte_synoptique_dwd_base64

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.content = _png_de_test(width=2000, height=1200)
    mock_session.get.return_value = mock_response

    data_uri = carte_synoptique_dwd_base64(session=mock_session, largeur_max_px=800)
    assert data_uri.startswith("data:image/jpeg;base64,")
    assert len(data_uri) > 100


def test_carte_synoptique_robuste_si_dwd_down() -> None:
    """Si DWD est inaccessible, retourne chaîne vide (ne casse pas le mail)."""
    from unittest.mock import MagicMock

    import requests

    from apps.veille.charts import carte_synoptique_dwd_base64

    mock_session = MagicMock()
    mock_session.get.side_effect = requests.ConnectionError("DWD down")
    assert carte_synoptique_dwd_base64(session=mock_session) == ""
