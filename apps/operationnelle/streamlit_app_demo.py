"""Page démo de l'App 2 Opérationnelle — vérification visuelle des cartes.

Lance Streamlit avec deux scénarios synthétiques (hiver / été) et rend
toutes les cartes de décisions correspondantes. Utile pour vérifier le
style/le rendu sans attendre les conditions réelles.

USAGE
-----

    streamlit run apps/operationnelle/streamlit_app_demo.py

Toggle le scénario en haut de la page (radio hiver / été).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
for p in (_REPO_ROOT, _SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import streamlit as st  # noqa: E402

from apps.operationnelle.decisions import evaluer_decisions, load_exploitation  # noqa: E402
from apps.operationnelle.demo import (  # noqa: E402
    quotidien_ete,
    quotidien_hiver,
    today_ete,
    today_hiver,
)
from apps.operationnelle.streamlit_app import _rendre_carte_decision  # noqa: E402

SCENARIOS = {
    "❄️ Hiver (gel + sec puis pluie)": (quotidien_hiver, today_hiver, "15 janvier 2026"),
    "☀️ Été (chaud + pluvieux + déficit)": (quotidien_ete, today_ete, "15 juillet 2026"),
}


def main() -> None:
    st.set_page_config(
        page_title="Démo — Décisions hebdo (App 2)",
        page_icon="🧪",
        layout="wide",
    )
    st.markdown(
        '<h2 style="margin:0 0 4px 0;font-size:24px;color:#2c3e50;">'
        "Démo — Cartes Décisions hebdo (vérification visuelle)"
        "</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="margin:0 0 12px 0;font-size:13px;color:#888;">'
        "Données synthétiques pour rendre l'ensemble des cartes possibles "
        "sur un scénario donné. Pour la vue prod, voir "
        "<code>streamlit_app.py</code>."
        "</p>",
        unsafe_allow_html=True,
    )

    scenario = st.radio(
        "Scénario",
        list(SCENARIOS.keys()),
        horizontal=True,
    )
    build_quot, build_today, libelle_date = SCENARIOS[scenario]
    quotidien = build_quot()
    today = build_today()

    try:
        exploitation = load_exploitation()
    except FileNotFoundError:
        st.error(
            "Configuration `config/exploitation.yaml` absente — impossible de générer les cartes."
        )
        return

    cartes = evaluer_decisions(quotidien, exploitation, today)

    st.caption(
        f"Date de référence : {libelle_date} · "
        f"{len(cartes)} carte{'s' if len(cartes) > 1 else ''} affichée"
        f"{'s' if len(cartes) > 1 else ''} sur 9 règles possibles."
    )

    if not cartes:
        st.warning("Aucune carte déclenchée — vérifier le scénario synthétique.")
        return

    for carte in cartes:
        _rendre_carte_decision(carte)


if __name__ == "__main__":
    main()
