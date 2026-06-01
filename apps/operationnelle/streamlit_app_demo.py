"""Page démo de l'App 2 Opérationnelle — vérification visuelle des guides.

Lance Streamlit avec deux scénarios synthétiques (hiver / été) et rend
tous les guides de décision correspondants. Utile pour vérifier le
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

from apps.operationnelle.decisions import (  # noqa: E402
    THEMES_LIBELLES,
    evaluer_decisions,
    grouper_par_theme,
    load_exploitation,
)
from apps.operationnelle.demo import (  # noqa: E402
    quotidien_ete,
    quotidien_hiver,
    today_ete,
    today_hiver,
)
from apps.operationnelle.streamlit_app import (  # noqa: E402
    _appliquer_overrides_session,
    _rendre_guide_decision,
)

SCENARIOS = {
    "❄️ Hiver (gel + sec puis pluie)": (quotidien_hiver, today_hiver, "15 janvier 2026"),
    "☀️ Été (chaud + pluvieux + déficit)": (quotidien_ete, today_ete, "15 juillet 2026"),
}


def main() -> None:
    st.set_page_config(
        page_title="Démo — Guides de décision hebdo (App 2)",
        page_icon="🧪",
        layout="wide",
    )
    st.markdown(
        '<h2 style="margin:0 0 4px 0;font-size:24px;color:#2c3e50;">'
        "Démo — Guides de décision hebdo (vérification visuelle)"
        "</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="margin:0 0 12px 0;font-size:13px;color:#888;">'
        "Données synthétiques pour rendre l'ensemble des guides possibles "
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
        exploitation_base = load_exploitation()
    except FileNotFoundError:
        st.error(
            "Configuration `config/exploitation.yaml` absente — impossible de générer les guides."
        )
        return

    # Applique les overrides session_state (sliders) avant évaluation,
    # comme dans la vue prod. Sans ça, bouger un slider ne change rien.
    exploitation = _appliquer_overrides_session(exploitation_base)
    guides = evaluer_decisions(quotidien, exploitation, today)

    nb_actifs = sum(1 for g in guides if g.active)
    accord_actif = "s" if nb_actifs > 1 else ""
    accord_appl = "s" if len(guides) > 1 else ""
    st.caption(
        f"Date de référence : {libelle_date} · {nb_actifs} actif{accord_actif} "
        f"sur {len(guides)} applicable{accord_appl} (les inactifs sont grisés ; "
        "leurs seuils restent ajustables)."
    )

    if not guides:
        st.warning("Aucun guide déclenché — vérifier le scénario synthétique.")
        return

    for theme, guides_theme in grouper_par_theme(guides):
        st.markdown(
            '<h4 style="margin:18px 0 6px 0;font-size:16px;color:#34495e;'
            'border-bottom:1px solid #eee;padding-bottom:4px;">'
            f"{THEMES_LIBELLES[theme]}"
            "</h4>",
            unsafe_allow_html=True,
        )
        for guide in guides_theme:
            _rendre_guide_decision(guide, exploitation)


if __name__ == "__main__":
    main()
