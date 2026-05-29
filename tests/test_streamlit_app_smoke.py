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
    for nom in ("COURBES", "Seuil", "bilan_tunnel_carry_over", "bilan_culture_carry_over"):
        assert hasattr(streamlit_app, nom), f"{nom} manquant dans streamlit_app"
