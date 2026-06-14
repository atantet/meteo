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

Source : ARPEGE run 00Z du jour → bilan sur 4 j depuis J+0 00Z. En priorité le
run MF-direct partagé par le mail (asset de release, ADR-0020), repli Open-Meteo
sinon — provenance affichée. ETP par le socle FAO ; bilan par
``meteo_socle.indices.bilan_hydrique``.
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


# Couleurs des séries du panneau flux (cf. figure_bilan_sol_complet → cohérence
# graphe/synthèse, palette Wong).
_COULEUR_ETM = "#D55E00"  # vermillon
_COULEUR_PLUIE = "#56B4E9"  # bleu
_COULEUR_DEFICIT = "#009E73"  # vert
_COULEUR_APPORT = "#009E73"  # vert — « Apport irrigation » du panneau réserves

# Système graphique de l'app (chrome) : marine + 2 gris + filet doux. La palette
# de DONNÉES du graphe (Wong, ci-dessus) reste distincte et intacte.
_ARDOISE = "#2c3e50"  # texte principal / accent
_GRIS_DOUX = "#6b7a8d"  # texte secondaire, légendes
_FILET = "#e3e8ee"  # filets, bordures de cartes
_CSS = f"""
<style>
/* Marge haute resserrée + largeur de lecture confortable. */
.block-container {{ padding-top: 2rem; padding-bottom: 3rem; max-width: 1180px; }}

/* En-tête. */
.atelier-titre {{ font-size: 26px; font-weight: 700; color: {_ARDOISE};
                  line-height: 1.15; margin: 0; }}
.atelier-sous-titre {{ font-size: 15px; color: {_GRIS_DOUX}; margin: 2px 0 4px 0; }}

/* Libellés de widgets (selectbox, slider) + onglets : homogènes. */
[data-testid="stSelectbox"] label p,
[data-testid="stSlider"] label p {{ font-size: 15px !important; font-weight: 600; color: #34495e; }}
button[data-baseweb="tab"] p {{ font-size: 16px !important; font-weight: 600; }}

/* Légendes : lisibles, aérées, gris doux. */
[data-testid="stCaptionContainer"] p {{ font-size: 13px; color: {_GRIS_DOUX}; line-height: 1.5; }}

/* Cartes (st.container(border=True)) : filet doux, coins arrondis, fond très clair. */
[data-testid="stVerticalBlockBorderWrapper"] > div {{ border-radius: 12px; }}
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {{ gap: 0.6rem; }}

/* En-tête d'expander : net. */
[data-testid="stExpander"] summary p {{ font-weight: 600; color: #34495e; font-size: 15px; }}

/* Filets de séparation discrets. */
hr {{ border-color: {_FILET}; margin: 1.2rem 0; }}
</style>
"""


def _titre_section(label: str) -> str:
    """Petit titre centré, souligné (bordure basse) — coiffe un groupe de valeurs."""
    return (
        "<div style='text-align:center;font-size:16px;font-weight:600;color:#34495e;"
        f"border-bottom:1px solid #cfd6dc;padding-bottom:4px;margin:0 0 10px 0;'>{label}</div>"
    )


def _grande_valeur(col, label: str, valeur: str, couleur_label: str) -> None:
    """Label **coloré** (= couleur du graphe, gros) + valeur en **gros et sombre**.

    La couleur est sur le label (pastille de légende) ; la valeur reste sombre
    pour rester lisible (un gros chiffre en bleu clair passerait mal sur blanc).
    """
    col.markdown(
        f"<div style='text-align:center;font-size:15px;font-weight:700;"
        f"color:{couleur_label};line-height:1.25;'>{label}</div>"
        f"<div style='text-align:center;font-size:30px;font-weight:700;"
        f"color:#2c3e50;line-height:1.1;'>{valeur}</div>",
        unsafe_allow_html=True,
    )


def _synthese_bilan(bilan, n_j: int, etm_col: str) -> None:
    """Synthèse sous la figure (disposition identique plein champ / sous abri).

    Sous le panneau **flux** (gauche) : les cumuls sur ``n_j`` j en gros, **labels
    colorés** comme le graphe (ETM vermillon, précipitations bleu, déficit vert).
    Sous le panneau **réserves + irrigations** (droite) : les déclenchements prévus.
    """
    etm_tot = float(bilan[etm_col].sum())
    pluie_tot = float(bilan["pluie_mm"].sum())
    deficit_tot = float(bilan["deficit_mm"].sum())
    # Doses d'irrigation réellement appliquées (jours d'apport) → « X mm + Y mm ».
    apports = [float(a) for a in bilan["apport_mm"] if float(a) > 0]
    doses = " + ".join(f"{a:.0f} mm" for a in apports) if apports else "-"
    with st.container(border=True):
        col_flux, col_res = st.columns(2)
        with col_flux:
            st.markdown(_titre_section(f"Cumuls sur {n_j} j"), unsafe_allow_html=True)
            m_etm, m_pluie, m_def = st.columns(3)
            _grande_valeur(m_etm, "ETM culture", f"{etm_tot:.1f} mm", _COULEUR_ETM)
            _grande_valeur(m_pluie, "Précipitations", f"{pluie_tot:.1f} mm", _COULEUR_PLUIE)
            _grande_valeur(m_def, "Déficit", f"{deficit_tot:.1f} mm", _COULEUR_DEFICIT)
        with col_res:
            st.markdown(_titre_section(f"Irrigation sur {n_j} j"), unsafe_allow_html=True)
            _grande_valeur(st, "Déclenchements prévus", doses, _COULEUR_APPORT)


def main() -> None:
    config = load_config()
    site = config["site"]
    lieu = site.get("lieu", "")
    horizon_court = int(config["source_meteo"]["horizon_court_jours"])

    now_utc = pd.Timestamp.now(tz="UTC")
    run_00z = calcul.run_00z(now_utc)  # 00Z du jour → bilan depuis J+0 00Z
    now_local = now_utc.tz_convert(site.get("tz", "Europe/Paris")).to_pydatetime()

    st.set_page_config(page_title="Bilan hydrique", page_icon="💧", layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)
    # En-tête : titre + sous-titre (date · lieu) hiérarchisés.
    date_fr = format_date_fr(now_local, capitalize_jour=True)
    sous_titre = f"{date_fr} · {lieu}" if lieu else date_fr
    st.markdown(
        f'<div class="atelier-titre">💧 Bilan hydrique</div>'
        f'<div class="atelier-sous-titre">{sous_titre}</div>',
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
            "RU initiale (% de la réserve utile)",
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
                "<div style='font-size:16px;color:#2c3e50;line-height:1.4;'>"
                f"<strong>Plein champ — {culture} ({stade_aff})</strong> · "
                f"réserve utile <strong>{ru_max:.0f} mm</strong> · "
                f"RFU <strong>{rfu:.0f} mm</strong> "
                "(irrigation quand l'épuisement atteint la RFU).</div>",
                unsafe_allow_html=True,
            )
            fig_pa = figure_bilan_sol_complet(bilan_pa, apport_max_mm=apport_max_mm)
            st.pyplot(fig_pa, use_container_width=True)
            _synthese_bilan(bilan_pa, n_j, "etm_mm")
        except KeyError as e:
            st.warning(f"Donnée manquante pour le bilan plein champ ({e}).")

    with tab_tu:
        st.caption(
            "Coefficient abri = facteur de réduction de l'ET₀ pour passer du climat "
            "extérieur au micro-climat de l'abri (coefficient fixe ET₀ abri/extérieur, "
            "Castilla 2013 ch. 4 ; Möller et al. 2004 — défaut 0,70, recalibration "
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
                "<div style='font-size:16px;color:#2c3e50;line-height:1.4;'>"
                f"<strong>Sous abri — {culture} ({stade_aff})</strong> · "
                f"coefficient abri <strong>{k_tunnel:.2f}</strong> · "
                f"réserve utile <strong>{ru_max:.0f} mm</strong> · "
                f"RFU <strong>{rfu:.0f} mm</strong> "
                "(irrigation quand l'épuisement atteint la RFU).</div>",
                unsafe_allow_html=True,
            )
            # Même disposition que le plein champ (figure complète flux + réserves).
            fig_tu = figure_bilan_sol_complet(bilan_tu, apport_max_mm=apport_max_mm)
            st.pyplot(fig_tu, use_container_width=True)
            _synthese_bilan(bilan_tu, n_j, "etm_tunnel_mm")
        except KeyError as e:
            st.warning(f"Donnée manquante pour le bilan tunnel ({e}).")

    # Séparateur net avant le pied « Sources ».
    st.divider()
    code_base = "https://github.com/atantet/meteo/blob/main/src/meteo_socle/indices"
    # Lien d'accès : la page GitHub de la release où le run MF est publié chaque
    # matin par le mail (ADR-0020) ; sinon la config qui définit la source/repli.
    lien_acces = (
        "https://github.com/atantet/meteo/releases/tag/arpege-atelier"
        if "Météo-France" in source_meteo
        else "https://github.com/atantet/meteo/blob/main/config/operationnelle.yaml"
    )
    age_h = (now_utc - run_00z).total_seconds() / 3600.0  # fraîcheur du run 00Z
    with st.expander("Sources"):
        st.markdown(
            f"""
- **Modèle** : ARPEGE Météo-France ~10 km, run 00Z du jour ({run_00z:%d/%m/%Y},
  il y a {age_h:.0f} h) — accès : [{source_meteo}]({lien_acces}).
- **ET₀** : formule FAO Penman-Monteith ([code]({code_base}/etp_fao.py)).
- **Vocabulaire (FAO-56)** : *réserve utile* (RU) = eau du sol mobilisable, entre
  la **capacité au champ** (sol ressuyé, réserve pleine) et le point de flétrissement ;
  *RFU* = fraction facilement utilisable sans stress. On irrigue quand l'épuisement
  atteint la RFU (réserve descendue à RU − RFU) et on recharge jusqu'à la capacité au champ.
- **Apport** : quand l'épuisement atteint la RFU, de quoi recharger jusqu'à la
  capacité au champ sans dépasser l'apport maximal permis ([code]({code_base}/bilan_hydrique.py)).
- **Coefficient cultural** : référentiel ARDEPI
  ([maraîchage](https://www.ardepi.fr/nos-services/vous-etes-irrigant/estimer-ses-besoins-en-eau/maraichage/)).
- **Coefficient sous abri** : Castilla, N. (2013). *Greenhouse Technology and
  Management* (2ᵉ éd.), chap. 4. Wallingford : CABI (ISBN 978-1-78064-103-4).
  · Möller, M., Tanny, J., Li, Y. & Cohen, S. (2004). « Measuring and predicting
  evapotranspiration in an insect-proof screenhouse ». *Agricultural and Forest
  Meteorology*, 127(1-2), 35-51.
            """
        )


if __name__ == "__main__":
    main()
