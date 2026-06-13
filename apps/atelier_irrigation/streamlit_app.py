"""Atelier irrigation — bilan hydrique sol complet (plein champ + tunnel).

Mini-dashboard Streamlit extrait de l'ancienne App 2 Opérationnelle (dissoute
dans le mail Veille, cf. ADR-0015). Le mail porte la vue semaine en statique ;
cet atelier garde la seule pièce qui exige de l'interactivité : le bilan
hydrique, où l'utilisateur fait varier culture, stade, texture de sol et
configuration tunnel pour voir les flux quotidiens (ETM, pluie, besoin
d'irrigation) et les jours de déclenchement.

USAGE
-----
    streamlit run apps/atelier_irrigation/streamlit_app.py
    # ou : python -m apps.atelier_irrigation

Source : ARPEGE Single Runs, run 00Z du jour → bilan sur 4 j depuis J+0 00Z.
ETP par le socle FAO ; bilan par ``meteo_socle.indices.bilan_hydrique``.
"""

from __future__ import annotations

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

from apps.atelier_irrigation import calcul  # noqa: E402
from apps.operationnelle.charts import (  # noqa: E402
    bilan_culture_carry_over,
    bilan_tunnel_carry_over,
    figure_bilan_sol_complet,
    figure_bilan_tunnel,
)
from apps.operationnelle.config import load_config  # noqa: E402
from apps.shared.dates_fr import format_date_fr  # noqa: E402
from meteo_socle.indices.bilan_hydrique import (  # noqa: E402
    PROFONDEUR_ENRACINEMENT_TYPIQUE,
    RU_PAR_CM_DE_TF,
)


@st.cache_data(ttl=3600)
def _obtenir_prevision(
    latitude: float,
    longitude: float,
    horizon_jours: int,
    run_utc: pd.Timestamp,
    url_partage: str | None,
) -> tuple[pd.DataFrame, str]:
    """Prévision (cache Streamlit) : run MF partagé (mail) prioritaire, repli OM."""
    return calcul.obtenir_prevision(
        latitude, longitude, horizon_jours, run_utc, url_partage=url_partage
    )


@st.cache_data
def _charger_coefficients_kc() -> dict[str, dict[str, float]]:
    return calcul.charger_coefficients()


def main() -> None:
    config = load_config()
    site = config["site"]
    lieu = site.get("lieu", "")
    horizon_court = int(config["source_meteo"]["horizon_court_jours"])

    now_utc = pd.Timestamp.now(tz="UTC")
    run_00z = calcul.run_00z(now_utc)  # 00Z du jour → bilan depuis J+0 00Z
    now_local = now_utc.tz_convert(site.get("tz", "Europe/Paris")).to_pydatetime()

    st.set_page_config(page_title="Bilan hydrique", page_icon="💧", layout="wide")
    titre = "Bilan hydrique du " + format_date_fr(now_local, capitalize_jour=False)
    # Localisation formatée comme dans le mail : séparateur « — », gris, plus
    # petit, poids normal (cf. apps/veille/email.py composer_html).
    lieu_html = (
        f'<span style="font-weight:400;color:#888;font-size:16px;"> — {lieu}</span>' if lieu else ""
    )
    st.markdown(
        f'<h2 style="margin:0 0 10px 0;font-size:24px;color:#2c3e50;">{titre}{lieu_html}</h2>',
        unsafe_allow_html=True,
    )

    url_partage = config["source_meteo"].get("arpege_partage_url") or None
    with st.spinner("Récupération de la prévision ARPEGE…"):
        try:
            prevision, source_meteo = _obtenir_prevision(
                site["latitude"], site["longitude"], horizon_court, run_00z, url_partage
            )
        except Exception as e:  # noqa: BLE001
            st.error(f"Prévision indisponible : {e}")
            st.stop()
    # Provenance affichée honnêtement : MF (run du mail, indépendant d'Open-Meteo)
    # ou repli Open-Meteo, + âge du run 00Z.
    age_h = (now_utc - run_00z).total_seconds() / 3600.0
    st.caption(f"Prévision : {source_meteo} · run {run_00z:%d/%m %HZ} (il y a {age_h:.0f} h).")

    # Indicateurs quotidiens depuis J+0 00Z (run 00Z) → 4 jours complets.
    quotidien = calcul.quotidien_du_jour(config, prevision, now_utc)
    if quotidien.empty:
        st.warning("Aucun jour complet dans la prévision courante.")
        st.stop()

    coefficients = _charger_coefficients_kc()
    cultures = sorted(coefficients.keys())
    defauts = calcul.PARAMS_DEFAUT
    default_culture = defauts["culture"] if defauts["culture"] in cultures else cultures[0]

    col_c, col_s = st.columns(2)
    with col_c:
        culture = st.selectbox("Culture", cultures, index=cultures.index(default_culture))
    with col_s:
        stades = list(coefficients[culture].keys())
        stade = st.selectbox("Stade phénologique", stades, index=0)

    # Stade en minuscule pour l'affichage entre parenthèses (le menu garde sa casse).
    stade_aff = stade[:1].lower() + stade[1:]
    kc = float(coefficients[culture][stade])
    st.caption(
        f"Kc culture = **{kc:.2f}** · référentiel ARDEPI plein champ. "
        "Sous abri, on garde le même Kc et on agit sur l'ET₀ via le coefficient abri."
    )

    with st.expander("Paramètres", expanded=False):
        textures = sorted(RU_PAR_CM_DE_TF.keys())
        default_texture = defauts["texture"] if defauts["texture"] in textures else textures[0]
        texture = st.selectbox(
            "Texture sol",
            textures,
            index=textures.index(default_texture),
            help="Détermine la rétention en eau par cm de terre fine.",
        )
        st.caption(
            f"Rétention = **{RU_PAR_CM_DE_TF[texture]:.2f} mm/cm** de terre fine · "
            "fixe la capacité de réserve utile (× profondeur d'enracinement de la culture)."
        )
        cailloux_pct = st.slider(
            "Fraction de cailloux (%)",
            min_value=0,
            max_value=50,
            value=int(defauts["fraction_cailloux"] * 100),
            help="Réduit la profondeur effective de terre fine.",
        )
        st.caption(
            f"Cailloux = **{cailloux_pct} %** · réduisent d'autant la profondeur de "
            "terre fine, donc la capacité de réserve utile."
        )
        fraction_cailloux = cailloux_pct / 100.0
        rfu_pct = st.slider(
            "Fraction RFU/RU (%)",
            min_value=40,
            max_value=80,
            value=int(defauts["ru_vers_rfu"] * 100),
            help="Fraction de la RU mobilisable sans stress. Typiquement 50-70 % selon la culture.",
        )
        st.caption(
            f"RFU/RU = **{rfu_pct} %** · part de la réserve mobilisable sans stress ; "
            "fixe le seuil de déclenchement (on irrigue quand l'épuisement l'atteint)."
        )
        ru_vers_rfu = rfu_pct / 100.0
        ru_init_pct = st.slider(
            "RU initiale (% de la capacité au champ)",
            min_value=0,
            max_value=100,
            value=int(defauts["fraction_ru_remplie_initial"] * 100),
            help="État de remplissage du sol au jour J+0. 100 % = sol à "
            "capacité au champ (situation de référence : l'irrigation vise "
            "à la maintenir).",
        )
        st.caption(
            f"RU initiale = **{ru_init_pct} %** · état de remplissage du sol au "
            "départ (J+0) ; 100 % = sol à capacité au champ."
        )
        fraction_ru_remplie_initial = ru_init_pct / 100.0
        apport_max_mm = float(
            st.slider(
                "Apport maximal (mm/jour)",
                min_value=5,
                max_value=100,
                value=int(defauts["apport_max_mm"]),
                step=5,
                help="Lame d'eau journalière maximale que le système peut apporter "
                "(≈ 1 L/h pendant 24 h pour 25 mm/j). Borne la dose d'irrigation et "
                "l'échelle de l'axe des apports.",
            )
        )

    # Doctrine FAO : le déclenchement est piloté par la RFU (slider RFU/RU
    # ci-dessus), pas par un seuil en mm → pas de garde-fou « dose minimale ».
    seuil_irrigation_mm = 0.0

    if culture not in PROFONDEUR_ENRACINEMENT_TYPIQUE:
        st.info(
            f"La culture « {culture} » n'a pas de profondeur d'enracinement "
            "référencée pour le bilan sol complet. Sélectionner une autre culture."
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
        apport_max_mm=apport_max_mm,
    )
    n_j = len(quotidien)
    tab_pa, tab_tu = st.tabs(["Plein champ", "Sous abri"])

    with tab_pa:
        try:
            bilan_pa = bilan_culture_carry_over(
                quotidien, k_etp_ratio=1.0, inclure_pluie=True, **params_sol
            )
            ru_max = float(bilan_pa["ru_max_mm"].iloc[0])
            rfu = float(bilan_pa["rfu_mm"].iloc[0])
            st.markdown(
                f"**Plein champ — {culture} ({stade_aff})** · "
                f"capacité au champ **{ru_max:.0f} mm** · RFU **{rfu:.0f} mm** "
                "(irrigation quand l'épuisement atteint la RFU)."
            )
            fig_pa = figure_bilan_sol_complet(bilan_pa, apport_max_mm=apport_max_mm)
            st.pyplot(fig_pa, use_container_width=True)
            pluie_tot = float(bilan_pa["pluie_mm"].sum())
            etm_tot = float(bilan_pa["etm_mm"].sum())
            nb_irrig = int(bilan_pa["irrigation_declenchee"].sum())
            deficit_tot = float(bilan_pa["deficit_mm"].sum())
            st.markdown(
                f"**Synthèse {n_j} j** : précipitations cumulées {pluie_tot:.1f} mm · "
                f"ETM {etm_tot:.1f} mm · Déficit total {deficit_tot:.1f} mm · "
                f"{nb_irrig} déclenchement(s) prévu(s)."
            )
        except KeyError as e:
            st.warning(f"Donnée manquante pour le bilan plein champ ({e}).")

    with tab_tu:
        st.caption(
            "Coefficient abri = facteur de réduction de l'ET₀ pour passer du climat "
            "extérieur au micro-climat de l'abri (coefficient fixe ET₀ abri/extérieur, "
            "Castilla 2013 ch. 4 ; Möller et al. 2009 — défaut 0,70, recalibration "
            "terrain à venir). Plus l'abri est ventilé, plus l'ET₀ se rapproche de "
            "l'extérieur."
        )
        preset_k = st.radio(
            "Ventilation de l'abri",
            options=(
                "Grand ouvert (portes + aérations)",
                "Aération modérée",
                "Fermé (peu d'échange)",
            ),
            index=1,
            horizontal=True,
            help="Détermine un coefficient abri approximatif ; ajustable par le slider.",
        )
        k_preset = {
            "Grand ouvert (portes + aérations)": 0.90,
            "Aération modérée": 0.70,
            "Fermé (peu d'échange)": 0.55,
        }[preset_k]
        k_tunnel = st.slider(
            "Coefficient abri (ET₀ sous abri / extérieur)",
            min_value=0.40,
            max_value=1.00,
            value=k_preset,
            step=0.05,
        )
        try:
            bilan_tu = bilan_tunnel_carry_over(quotidien, k_tunnel=k_tunnel, **params_sol)
            ru_max = float(bilan_tu["ru_max_mm"].iloc[0])
            rfu = float(bilan_tu["rfu_mm"].iloc[0])
            st.markdown(
                f"**Sous abri — {culture} ({stade_aff})** · coefficient abri **{k_tunnel:.2f}** · "
                f"capacité au champ **{ru_max:.0f} mm** · RFU **{rfu:.0f} mm** "
                "(irrigation quand l'épuisement atteint la RFU)."
            )
            fig_tu = figure_bilan_tunnel(bilan_tu, apport_max_mm=apport_max_mm)
            st.pyplot(fig_tu, use_container_width=True)
            etm_tot = float(bilan_tu["etm_tunnel_mm"].sum())
            nb_irrig = int(bilan_tu["irrigation_declenchee"].sum())
            deficit_tot = float(bilan_tu["deficit_mm"].sum())
            st.markdown(
                f"**Synthèse {n_j} j** : ETM cumulée {etm_tot:.1f} mm · "
                f"Déficit total {deficit_tot:.1f} mm · "
                f"{nb_irrig} déclenchement(s) prévu(s)."
            )
        except KeyError as e:
            st.warning(f"Donnée manquante pour le bilan tunnel ({e}).")

    code_base = "https://github.com/atantet/meteo/blob/main/src/meteo_socle/indices"
    with st.expander("Sources"):
        st.markdown(
            f"""
- **Modèle** : ARPEGE Météo-France ~10 km (Open-Meteo *Single Runs*, run 00Z
  du jour {run_00z.strftime("%d/%m %HZ")}, horizon {horizon_court} j, UTC).
- **ETP** : formule FAO Penman-Monteith ([code]({code_base}/etp_fao.py)).
- **Bilan** : réserve utile (TAW) / RFU (RAW), irrigation quand l'épuisement
  atteint la RFU avec recharge à la capacité au champ — cadre FAO 56, ch. 8
  ([code]({code_base}/bilan_hydrique.py)).
- **Kc** : référentiel ARDEPI
  ([maraîchage](https://www.ardepi.fr/nos-services/vous-etes-irrigant/estimer-ses-besoins-en-eau/maraichage/)).
- **Coefficient abri** : coefficient fixe ET₀ sous abri/extérieur — Castilla
  (2013, ch. 4) ; Möller et al. (2009). Défaut 0,70.
- **Cache** : 1 h sur la prévision. Rafraîchir = recharger la page.
            """
        )


if __name__ == "__main__":
    main()
