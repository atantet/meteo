"""Smoke test : l'app Streamlit s'importe sans erreur.

Garantit que Streamlit Community Cloud ne va pas planter au cold start
à cause d'un import cassé (renommage de module, dépendance manquante…)
sans qu'on s'en rende compte localement.

On n'invoque pas ``main()`` — ça exigerait un runtime Streamlit actif.
"""

from __future__ import annotations


def test_streamlit_app_importable():
    """L'entrypoint Streamlit doit s'importer et exposer main()."""
    from apps.operationnelle import streamlit_app

    assert hasattr(streamlit_app, "main")
    assert callable(streamlit_app.main)


def test_streamlit_app_importe_modules_critiques():
    """Vérifie la présence des imports clés (régression : disparition silencieuse)."""
    from apps.operationnelle import streamlit_app

    # Modules métier socle et apps que le main attend.
    for nom in ("Seuil", "bilan_tunnel_carry_over", "bilan_culture_carry_over"):
        assert hasattr(streamlit_app, nom), f"{nom} manquant dans streamlit_app"


def test_slot_now_canonique():
    """_slot_now : horodatage stable du créneau (06Z matin / 18Z après-midi)."""
    import pandas as pd

    from apps.operationnelle.streamlit_app import _slot_now

    # Matin (créneau 05:30-17:30 UTC) → 06Z du jour.
    assert _slot_now(pd.Timestamp("2024-06-15 09:00", tz="UTC")) == pd.Timestamp(
        "2024-06-15 06:00", tz="UTC"
    )
    # Après-midi (≥ 17:30 UTC) → 18Z du jour.
    assert _slot_now(pd.Timestamp("2024-06-15 18:00", tz="UTC")) == pd.Timestamp(
        "2024-06-15 18:00", tz="UTC"
    )
    # Nuit (< 05:30 UTC) → 18Z de la veille (créneau après-midi de la veille).
    assert _slot_now(pd.Timestamp("2024-06-15 03:00", tz="UTC")) == pd.Timestamp(
        "2024-06-14 18:00", tz="UTC"
    )


def test_grille_tendance_proba_en_ligne_dediee(monkeypatch):
    """La proba pluie a sa **propre ligne** « ECMWF IFS-ENS » (grandeur
    d'ensemble), pas sur la ligne AROME, et n'apparaît plus dans les cellules
    pluie des modèles déterministes (régression : misattribution à un modèle).
    """
    import numpy as np
    import pandas as pd

    from apps.operationnelle import streamlit_app

    captures: list[str] = []
    monkeypatch.setattr(streamlit_app.st, "markdown", lambda html, **k: captures.append(html))

    def _serie(avec_proba: bool) -> pd.DataFrame:
        idx = pd.date_range("2026-06-15 00:00", periods=48, freq="h", tz="UTC")
        d = pd.DataFrame(
            {
                "temperature_2m": np.full(48, 288.0),
                "humidite_relative": np.full(48, 0.8),
                "precipitation": np.tile([0.0] * 5 + [2.0] + [0.0] * 6, 4),
                "vitesse_vent_10m": np.full(48, 3.0),
                "rafales_vent_10m": np.full(48, 6.0),
                "direction_vent_10m": np.full(48, 270.0),
                "weather_code": np.zeros(48, dtype=int),
                "couverture_nuageuse": np.full(48, 0.3),
            },
            index=idx,
        )
        if avec_proba:
            d["probabilite_pluie_pct"] = np.tile([0, 0, 0, 0, 0, 80, 0, 0, 0, 0, 0, 0], 4).astype(
                float
            )
        return d

    series = [
        ("ARPEGE", _serie(avec_proba=False), None),
        ("ECMWF IFS", _serie(avec_proba=True), None),
    ]
    streamlit_app._afficher_grille_tendance(series, horizon_jours=2, tz_locale="UTC")
    html = "\n".join(captures)

    assert "Proba pluie" in html  # ligne dédiée présente
    assert "ECMWF IFS-ENS" in html  # libellée par sa vraie source
    assert ">80<" in html  # la proba est bien rendue
    # La proba (« % ») n'est PAS dans les cellules pluie (bloc avant la ligne Proba).
    bloc_pluie = html.split("Proba pluie")[0].split(">Pluie<")[-1]
    assert "%" not in bloc_pluie
