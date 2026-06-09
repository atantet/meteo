"""Atelier irrigation — bilan hydrique sol complet (plein champ + tunnel).

Mini-dashboard Streamlit extrait de l'ancienne App 2 Opérationnelle (dissoute
dans le mail Veille, cf. ADR-0015). Le mail porte désormais guides + tendance +
cartes en statique ; cet atelier garde la seule pièce qui exige de
l'interactivité : le **bilan hydrique**, où l'utilisateur fait varier culture,
stade, texture de sol et configuration tunnel pour voir l'évolution de la réserve
utile et les déclenchements d'irrigation.

USAGE
-----
    streamlit run apps/atelier_irrigation/streamlit_app.py
    # ou : python -m apps.atelier_irrigation

Source : ARPEGE Single Runs (run déterministe du créneau, ADR-0011), horizon
court. ETP par le socle FAO ; bilan par ``meteo_socle.indices.bilan_hydrique``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Permet l'import direct quand on lance via `streamlit run`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
for p in (_REPO_ROOT, _SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from apps.operationnelle.charts import (  # noqa: E402
    bilan_culture_carry_over,
    bilan_tunnel_carry_over,
    figure_bilan_sol_complet,
    figure_bilan_tunnel,
)
from apps.operationnelle.config import load_config  # noqa: E402
from apps.operationnelle.indicateurs import (  # noqa: E402
    calculer_indicateurs_quotidiens,
    jours_complets_seulement,
)
from meteo_socle.indices.bilan_hydrique import (  # noqa: E402
    PROFONDEUR_ENRACINEMENT_TYPIQUE,
    RU_PAR_CM_DE_TF,
)
from meteo_socle.sources.openmeteo_runs import (  # noqa: E402
    ARPEGE,
    VARS_MONO_MODELE,
    OpenMeteoSingleRuns,
    creneau_run,
    runs_du_creneau,
)

KC_JSON_PATH = _SRC / "meteo_socle" / "indices" / "coefficients_culturaux_ardepi.json"


def _slot_now(now_utc: pd.Timestamp) -> pd.Timestamp:
    """Horodatage canonique du créneau courant (clé de cache stable)."""
    creneau, jour = creneau_run(now_utc)
    return jour + pd.Timedelta(hours=6 if creneau == "matin" else 18)


@st.cache_data(ttl=3600)
def _fetch_arpege(
    latitude: float, longitude: float, horizon_jours: int, slot_now: pd.Timestamp
) -> pd.DataFrame:
    """Run ARPEGE déterministe du créneau (ADR-0011), horizon court, forward-only."""
    src = OpenMeteoSingleRuns()
    creneau, jour = creneau_run(slot_now)
    run = runs_du_creneau(creneau, jour)[ARPEGE]
    df = src.obtenir_run(ARPEGE, run, latitude, longitude, horizon_jours, VARS_MONO_MODELE)
    if df is None or df.empty:
        raise RuntimeError(f"Run ARPEGE {run} muet.")
    return df


@st.cache_data
def _charger_coefficients_kc() -> dict[str, dict[str, float]]:
    with open(KC_JSON_PATH) as f:
        return json.load(f)


def main() -> None:
    config = load_config()
    site = config["site"]
    horizon_court = int(config["source_meteo"]["horizon_court_jours"])

    st.set_page_config(page_title="Atelier irrigation", page_icon="💧", layout="wide")
    st.markdown(
        '<h2 style="margin:0 0 4px 0;font-size:24px;color:#2c3e50;">'
        "Atelier irrigation — bilan hydrique</h2>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Évolution de la réserve utile et déclenchements d'irrigation sur la "
        f"prévision {horizon_court} j (ARPEGE). Faites varier culture, sol et "
        "tunnel pour comparer les scénarios. Complément interactif du mail Veille."
    )

    now_utc = pd.Timestamp.now(tz="UTC")
    slot_now = _slot_now(now_utc)
    with st.spinner("Récupération de la prévision ARPEGE…"):
        try:
            prevision = _fetch_arpege(site["latitude"], site["longitude"], horizon_court, slot_now)
        except Exception as e:  # noqa: BLE001
            st.error(f"Prévision indisponible : {e}")
            st.stop()

    quotidien = calculer_indicateurs_quotidiens(prevision, config, now_utc=now_utc)
    quotidien = jours_complets_seulement(quotidien, prevision)
    if quotidien.empty:
        st.warning("Aucun jour complet dans la prévision courante.")
        st.stop()

    coefficients = _charger_coefficients_kc()
    cultures = sorted(coefficients.keys())
    default_culture = "Tomate" if "Tomate" in cultures else cultures[0]

    col_c, col_s = st.columns(2)
    with col_c:
        culture = st.selectbox("Culture", cultures, index=cultures.index(default_culture))
    with col_s:
        stades = list(coefficients[culture].keys())
        stade = st.selectbox("Stade phénologique", stades, index=0)

    kc = float(coefficients[culture][stade])
    st.caption(
        f"Kc culture = **{kc:.2f}** · Référentiel ARDEPI plein champ. "
        "Sous tunnel, on garde le même Kc et on agit sur l'ET₀ via k_tunnel."
    )

    with st.expander("Paramètres sol (partagés plein champ + tunnel)", expanded=False):
        textures = sorted(RU_PAR_CM_DE_TF.keys())
        default_texture = (
            "Terres limono-argileuses" if "Terres limono-argileuses" in textures else textures[0]
        )
        texture = st.selectbox(
            "Texture sol",
            textures,
            index=textures.index(default_texture),
            help="Détermine la rétention par cm de terre fine.",
        )
        fraction_cailloux = (
            st.slider(
                "Fraction de cailloux (%)",
                min_value=0,
                max_value=50,
                value=5,
                help="Réduit la profondeur effective de terre fine.",
            )
            / 100.0
        )
        fraction_ru_remplie_initial = (
            st.slider(
                "RU initiale (% de la capacité au champ)",
                min_value=0,
                max_value=100,
                value=70,
                help="État de remplissage du sol au jour J. 100 % = sol "
                "complètement humide après pluie ou irrigation récente.",
            )
            / 100.0
        )
        ru_vers_rfu = (
            st.slider(
                "Fraction RFU/RU (%)",
                min_value=40,
                max_value=80,
                value=60,
                help="Fraction de la RU mobilisable sans stress. "
                "Typiquement 50-70 % selon la culture.",
            )
            / 100.0
        )
        seuil_irrigation_mm = st.slider(
            "Seuil de déclenchement irrigation (mm)",
            min_value=2.0,
            max_value=30.0,
            value=10.0,
            step=1.0,
            help="Si le déficit en RFU dépasse ce seuil, irrigation "
            "déclenchée (recharge à capacité au champ).",
        )

    if culture not in PROFONDEUR_ENRACINEMENT_TYPIQUE:
        st.info(
            f"La culture « {culture} » n'a pas de profondeur d'enracinement "
            "référencée pour le bilan sol complet. Sélectionner une culture "
            "présente dans `PROFONDEUR_ENRACINEMENT_TYPIQUE`."
        )
        return

    params_sol = dict(
        texture=texture,
        fraction_cailloux=fraction_cailloux,
        culture=culture,
        stade=stade,
        fraction_ru_remplie_initial=fraction_ru_remplie_initial,
        ru_vers_rfu=ru_vers_rfu,
        seuil_irrigation_mm=seuil_irrigation_mm,
    )
    tab_pa, tab_tu = st.tabs(["Plein champ", "Sous tunnel"])

    with tab_pa:
        try:
            bilan_pa = bilan_culture_carry_over(
                quotidien, k_etp_ratio=1.0, inclure_pluie=True, **params_sol
            )
            fig_pa = figure_bilan_sol_complet(
                bilan_pa,
                culture,
                stade,
                seuil_irrigation_mm,
                titre_contexte="Bilan plein champ",
                afficher_pluie=True,
                figsize=(5.5, 3.0),
            )
            col_p, _ = st.columns([2, 1])
            with col_p:
                st.pyplot(fig_pa, use_container_width=True)
            pluie_tot = float(bilan_pa["pluie_mm"].sum())
            etm_tot = float(bilan_pa["etm_mm"].sum())
            nb_irrig = int(bilan_pa["irrigation_declenchee"].sum())
            besoin_tot = float(bilan_pa["besoin_irrigation_mm"].sum())
            st.markdown(
                f"**Synthèse {horizon_court} j plein champ** : "
                f"pluie cumulée {pluie_tot:.1f} mm · "
                f"ETM {etm_tot:.1f} mm · "
                f"besoin irrigation total {besoin_tot:.1f} mm · "
                f"{nb_irrig} déclenchement(s) prévu(s)."
            )
        except KeyError as e:
            st.warning(f"Donnée manquante pour le bilan plein champ ({e}).")

    with tab_tu:
        st.caption(
            "Coefficient k_tunnel : facteur de réduction de l'ET₀ pour passer du "
            "climat extérieur au micro-climat tunnel."
        )
        preset_k = st.radio(
            "Configuration tunnel (preset)",
            options=(
                "Ouvert (portes jour + nuit)",
                "Froid standard (défaut)",
                "Fermé peu ventilé",
            ),
            index=1,
            horizontal=True,
            help="Sélectionne k_tunnel approximatif ; ajustable par le slider.",
        )
        k_preset = {
            "Ouvert (portes jour + nuit)": 0.90,
            "Froid standard (défaut)": 0.70,
            "Fermé peu ventilé": 0.55,
        }[preset_k]
        k_tunnel = st.slider(
            "k_tunnel — coef. ETP tunnel/extérieur",
            min_value=0.40,
            max_value=1.00,
            value=k_preset,
            step=0.05,
        )
        try:
            bilan_tu = bilan_tunnel_carry_over(quotidien, k_tunnel=k_tunnel, **params_sol)
            fig_tu = figure_bilan_tunnel(
                bilan_tu, culture, stade, seuil_irrigation_mm, figsize=(5.5, 3.0)
            )
            col_t, _ = st.columns([2, 1])
            with col_t:
                st.pyplot(fig_tu, use_container_width=True)
            etm_tot = float(bilan_tu["etm_tunnel_mm"].sum())
            nb_irrig = int(bilan_tu["irrigation_declenchee"].sum())
            besoin_tot = float(bilan_tu["besoin_irrigation_mm"].sum())
            st.markdown(
                f"**Synthèse {horizon_court} j sous tunnel (k_tunnel = {k_tunnel:.2f})** : "
                f"ETM cumulée {etm_tot:.1f} mm · "
                f"besoin irrigation total {besoin_tot:.1f} mm · "
                f"{nb_irrig} déclenchement(s) prévu(s)."
            )
        except KeyError as e:
            st.warning(f"Donnée manquante pour le bilan tunnel ({e}).")

    with st.expander("Vérifier les sources"):
        creneau, jour = creneau_run(slot_now)
        run = runs_du_creneau(creneau, jour)[ARPEGE]
        st.markdown(
            f"""
- **Modèle** : ARPEGE Météo-France ~10 km (Open-Meteo *Single Runs*, run
  déterministe {run.strftime("%d/%m %HZ")}, horizon {horizon_court} j, UTC).
- **ETP** : socle FAO Penman-Monteith (``meteo_socle.indices.etp_fao``), pas le
  champ du fournisseur.
- **Bilan** : ``meteo_socle.indices.bilan_hydrique`` (FAO 56, carry-over RU jour
  par jour, irrigation virtuelle à capacité au champ si déficit RFU > seuil).
- **Kc** : référentiel ARDEPI Provence
  (``coefficients_culturaux_ardepi.json``).
- **Site** : {site["latitude"]:.4f}°N, {site["longitude"]:.4f}°W, altitude
  {site["altitude"]} m.
- **Cache** : 1 h sur la prévision. Rafraîchir = recharger la page.
            """
        )


if __name__ == "__main__":
    main()
