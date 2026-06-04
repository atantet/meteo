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
