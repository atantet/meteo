"""Vue dashboard Streamlit — App 2 Opérationnelle.

Entry point pour Streamlit Cloud et `streamlit run`.

USAGE
-----

Local :
    streamlit run apps/operationnelle/streamlit_app.py
    # ou : python -m apps.operationnelle

Streamlit Community Cloud :
    Main file path = ``apps/operationnelle/streamlit_app.py``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Permet l'import direct quand on lance via `streamlit run` (qui ne
# passe pas par apps/__init__.py systématiquement).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
for p in (_REPO_ROOT, _SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from apps.operationnelle.charts import (  # noqa: E402
    COURBES,
    Seuil,
    bilan_tunnel_carry_over,
    figure_bilan_culture,
    figure_bilan_tunnel,
    figure_calendrier_semis,
    figure_indicateur,
)
from apps.operationnelle.config import load_config  # noqa: E402
from apps.operationnelle.indicateurs import (  # noqa: E402
    calculer_indicateurs_quotidiens,
    jours_complets_seulement,
)
from apps.operationnelle.ui_helpers import (  # noqa: E402
    preparer_table_affichage,
    styler_ligne,
)
from apps.shared.dates_fr import format_horodatage_fr  # noqa: E402
from meteo_socle.indices import pepiniere as _pepi  # noqa: E402
from meteo_socle.indices.bilan_hydrique import (  # noqa: E402
    PROFONDEUR_ENRACINEMENT_TYPIQUE,
    RU_PAR_CM_DE_TF,
)
from meteo_socle.sources.openmeteo import OpenMeteoForecast  # noqa: E402

KC_JSON_PATH = _SRC / "meteo_socle" / "indices" / "coefficients_culturaux_ardepi.json"


@st.cache_data(ttl=3600)
def _fetch_prevision(
    latitude: float, longitude: float, horizon_jours: int, modele: str
) -> pd.DataFrame:
    """Fetch Open-Meteo, cache 1 h pour limiter les requêtes."""
    src = OpenMeteoForecast(modele=modele)
    return src.obtenir_prevision(latitude, longitude, horizon_jours)


@st.cache_data
def _charger_coefficients_kc() -> dict[str, dict[str, float]]:
    """Charge les coefficients culturaux ARDEPI."""
    with open(KC_JSON_PATH) as f:
        return json.load(f)


def main() -> None:
    config = load_config()
    site = config["site"]
    ui_cfg = config["ui"]

    st.set_page_config(
        page_title=ui_cfg["titre"],
        page_icon="🌦️",
        layout="wide",
    )
    st.title(ui_cfg["titre"])
    maintenant = pd.Timestamp.now(tz="UTC").to_pydatetime()
    st.caption(
        f"{format_horodatage_fr(maintenant, site.get('tz', 'Europe/Paris'))} · "
        f"site {site['latitude']:.4f} N, {site['longitude']:.4f} W, alt {site['altitude']} m"
    )

    horizon = config["source_meteo"]["horizon_max_jours"]
    modele = config["source_meteo"]["modeles"][0]

    with st.spinner(f"Récupération prévision Open-Meteo ({modele}, {horizon} j)…"):
        try:
            prevision = _fetch_prevision(site["latitude"], site["longitude"], horizon, modele)
        except Exception as e:  # noqa: BLE001
            st.error(f"Erreur de récupération de la prévision : {e}")
            st.stop()

    now_utc = pd.Timestamp.now(tz="UTC")
    quotidien = calculer_indicateurs_quotidiens(prevision, config, now_utc=now_utc)
    quotidien = jours_complets_seulement(quotidien, prevision)

    # Premier pas de prévision (T+0) affiché explicitement.
    if not prevision.empty:
        t0 = prevision.index[prevision.index >= now_utc][0]
        t0_loc = t0.tz_convert(site.get("tz", "Europe/Paris"))
        st.caption(
            f"Premier pas de prévision (T+0) : "
            f"**{t0.strftime('%H:%M')} UTC** ({t0_loc.strftime('%H:%M')} heure locale)"
        )

    # ----- Courbes 7 j (vue principale, en onglets) -----
    st.subheader("Prévision 7 jours — courbes par indicateur")
    st.caption(
        "Pour les T° : courbe pointillée gris = normale OMM 1991-2020. "
        "Zone ombrée rouge = au-dessus de la normale, bleu = en-dessous."
    )

    # Seuils dynamiques tirés de la config alertes : gel sur T_min,
    # canicule sur T_max. Affichés seulement si la courbe les traverse.
    alertes_cfg = config["alertes"]
    seuils_par_colonne: dict[str, list[Seuil]] = {}
    if alertes_cfg.get("gel", {}).get("actif"):
        seuils_par_colonne["t_min_celsius"] = [
            Seuil(
                float(alertes_cfg["gel"]["seuil_celsius"]),
                f"Seuil gel ({alertes_cfg['gel']['seuil_celsius']:g} °C)",
                "#2980b9",
            )
        ]
    if alertes_cfg.get("canicule", {}).get("actif"):
        seuils_par_colonne["t_max_celsius"] = [
            Seuil(
                float(alertes_cfg["canicule"]["seuil_celsius"]),
                f"Seuil canicule ({alertes_cfg['canicule']['seuil_celsius']:g} °C)",
                "#c0392b",
            )
        ]

    courbes_dispo = [c for c in COURBES if c.colonne in quotidien.columns]
    onglets = st.tabs([c.titre for c in courbes_dispo])
    for tab, cfg in zip(onglets, courbes_dispo, strict=False):
        with tab:
            fig = figure_indicateur(
                quotidien, cfg, seuils_extra=seuils_par_colonne.get(cfg.colonne)
            )
            st.pyplot(fig, use_container_width=True)

    # ----- Bilan hydrique culture (nouveau) -----
    st.subheader("Bilan hydrique par culture")
    st.caption(
        "ET_c = Kc × ET₀ (FAO 56). Pluie cumulée comparée à l'ET_c cumulée "
        "sur la fenêtre de prévision. Coefficients Kc issus du référentiel "
        "ARDEPI (Provence) — à recaler localement pour la Bretagne."
    )

    coefficients = _charger_coefficients_kc()
    cultures = sorted(coefficients.keys())
    # Tomate en défaut pour rester aligné avec l'orientation App (mildiou).
    default_culture = "Tomate" if "Tomate" in cultures else cultures[0]

    col_c, col_s = st.columns(2)
    with col_c:
        culture = st.selectbox("Culture", cultures, index=cultures.index(default_culture))
    with col_s:
        stades = list(coefficients[culture].keys())
        stade = st.selectbox("Stade phénologique", stades, index=0)

    kc = float(coefficients[culture][stade])
    st.caption(
        f"Kc = **{kc:.2f}** · "
        f"hypothèse : pas de stress hydrique, ET_c = Kc · ET₀. "
        f"Modèle simplifié sans report de réserve utile du sol "
        f"(voir `meteo_socle.indices.bilan_hydrique` pour la version complète)."
    )

    if "etp_mm" in quotidien.columns and "pluie_24h_mm" in quotidien.columns:
        fig_bh = figure_bilan_culture(quotidien, culture, stade, kc)
        st.pyplot(fig_bh, use_container_width=True)

    # ----- Bilan hydrique sous tunnel -----
    st.subheader("Bilan hydrique sous tunnel (modèle sol complet)")
    st.caption(
        "Pluie = 0 (couverture). ETP réduite par un coefficient tunnel : "
        "ET₀_tunnel = k × ET₀_extérieur. Modèle FAO 56 avec carry-over RU "
        "jour par jour : si le besoin dépasse le seuil, irrigation virtuelle "
        "à capacité au champ, sinon on continue avec la RU résiduelle."
    )

    with st.expander("Paramètres tunnel et sol", expanded=False):
        # Presets rapides — l'utilisateur peut ensuite ajuster fin.
        preset_k = st.radio(
            "Configuration tunnel (preset)",
            options=("Ouvert (portes jour + nuit)", "Froid standard (défaut)", "Fermé peu ventilé"),
            index=1,
            horizontal=True,
            help="Cf. ADR-0008. Sélectionne k_tunnel approximatif ; "
            "ajustable par le slider en dessous.",
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
            help="0.70 défaut (médiane littérature tunnel froid ventilé). Castilla 2013 § 4.",
        )
        textures = sorted(RU_PAR_CM_DE_TF.keys())
        # Défaut limono-argileuse — typique sols armoricains.
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

    # Vérifier qu'on a la culture côté bilan_hydrique aussi (mapping
    # ARDEPI peut différer légèrement de KC).
    if culture in PROFONDEUR_ENRACINEMENT_TYPIQUE:
        try:
            bilan = bilan_tunnel_carry_over(
                quotidien,
                k_tunnel=k_tunnel,
                texture=texture,
                fraction_cailloux=fraction_cailloux,
                culture=culture,
                stade=stade,
                fraction_ru_remplie_initial=fraction_ru_remplie_initial,
                ru_vers_rfu=ru_vers_rfu,
                seuil_irrigation_mm=seuil_irrigation_mm,
            )
            fig_bt = figure_bilan_tunnel(bilan, culture, stade, seuil_irrigation_mm)
            st.pyplot(fig_bt, use_container_width=True)

            # Synthèse 7 j.
            etm_total = float(bilan["etm_tunnel_mm"].sum())
            nb_irrig = int(bilan["irrigation_declenchee"].sum())
            besoin_total = float(bilan["besoin_irrigation_mm"].sum())
            st.markdown(
                f"**Synthèse 7 j sous tunnel** : "
                f"ETM cumulée {etm_total:.1f} mm · "
                f"besoin total irrigation {besoin_total:.1f} mm · "
                f"{nb_irrig} déclenchement(s) prévu(s)."
            )
        except KeyError as e:
            st.warning(
                f"Donnée manquante pour le bilan tunnel ({e}). "
                "Vérifier que la culture est référencée côté "
                "PROFONDEUR_ENRACINEMENT_TYPIQUE."
            )
    else:
        st.info(
            f"La culture « {culture} » n'a pas de profondeur d'enracinement "
            "référencée pour le bilan sol complet. Sélectionner une culture "
            "présente dans `PROFONDEUR_ENRACINEMENT_TYPIQUE`."
        )

    # ----- Pépinière : calendrier semis interactif -----
    st.subheader("Pépinière — calendrier semis")
    st.caption(
        "Choisir une date de plantation cible (typiquement après le risque "
        "de gel) ; le calendrier remonte la durée d'élevage médiane par "
        "culture (CTIFL/GRAB/ITAB). Cf. [ADR-0009] pour le périmètre v0."
    )

    import datetime as _dt

    col_pep1, col_pep2 = st.columns(2)
    with col_pep1:
        date_plantation_cible = st.date_input(
            "Date de plantation cible",
            value=_dt.date(_dt.date.today().year, 5, 15),
            help="Par défaut 15 mai (équivalent ~90ᵉ percentile dernier gel "
            "Pleine-Fougères). Voir le rapport Climato pour la distribution exacte.",
        )
    with col_pep2:
        marge = st.slider(
            "Marge d'élevage (jours)",
            min_value=0,
            max_value=21,
            value=7,
            help="Sécurité ajoutée à la durée d'élevage médiane pour "
            "absorber les retards (germination lente, météo défavorable).",
        )

    pep_cultures = _pepi.cultures_disponibles()
    cultures_choisies = st.multiselect(
        "Cultures à semer (vide = toutes les cultures sensibles au gel)",
        options=pep_cultures,
        default=[],
    )
    cultures_arg = cultures_choisies if cultures_choisies else None
    cal = _pepi.calendrier_semis(
        date_plantation_cible, cultures=cultures_arg, marge_securite_j=marge
    )
    cal_df = pd.DataFrame(cal)
    if not cal_df.empty:
        # Figure Gantt timeline.
        fig_cal = figure_calendrier_semis(cal)
        st.pyplot(fig_cal, use_container_width=True)
        # Tableau détaillé en complément.
        with st.expander("Tableau détaillé", expanded=False):
            cal_df["Semis"] = cal_df["date_semis"].apply(lambda d: d.strftime("%a %d %b"))
            cal_df["Plantation"] = cal_df["date_plantation"].apply(lambda d: d.strftime("%a %d %b"))
            cal_df["Durée (j)"] = cal_df["duree_elevage_j"]
            affichage = cal_df[["culture", "Semis", "Plantation", "Durée (j)"]].rename(
                columns={"culture": "Culture"}
            )
            affichage = affichage.sort_values("Semis").reset_index(drop=True)
            st.dataframe(affichage, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune culture sélectionnée.")

    # ----- Tableau détaillé (replié par défaut) -----
    with st.expander("Tableau détaillé jour par jour", expanded=False):
        st.caption(
            "Coloration : T° rouge si gel/canicule franchi · "
            "rafales orange si vent fort · pluie bleu si intense · "
            "Smith mildiou orange info."
        )
        table = preparer_table_affichage(quotidien, tz=site["tz"])
        styler = table.style.apply(lambda row: styler_ligne(row, config["alertes"]), axis=1)
        st.dataframe(styler, use_container_width=True)

    # ----- Transparence sources (principe #5) -----
    if ui_cfg.get("inclure_sources_brutes", True):
        with st.expander("Vérifier les sources (transparence — principe #5)"):
            st.markdown(
                f"""
- **Source de données** : Open-Meteo (REST, sans authentification).
  Modèle ``{modele}`` compose AROME France HD 1.3 km (0-2 j),
  ICON-EU ou ARPEGE (2-4 j), ECMWF IFS 9 km (4-{horizon} j).
- **ETP** : calculée par le socle FAO Penman-Monteith horaire
  (``meteo_socle.indices.etp_fao.calcul_etp``), **pas** reprise du
  champ ``etp_open_meteo`` du fournisseur, pour cohérence avec
  les autres apps.
- **Normales T° (1991-2020 OMM)** : extraites de
  ``data/climato/normale_jour_lapetiteclaye.csv`` (ERA5 30 ans —
  voir `scripts/compute_normale_jour.py`). Disponibles pour T° min,
  T° max et T° moyenne — overlay automatique sur les courbes.
- **Direction dominante** : moyenne vectorielle horaire pondérée
  par la vitesse.
- **Smith mildiou (ADR-0007)** : indicateur informationnel pour
  tomate sous abri. Détecte les fenêtres où T_min ≥ 10 °C ET
  h HR ≥ 90 % ≥ 11 h sur 2 jours consécutifs. Calculé via le
  module socle ``meteo_socle.indices.mildiou`` à partir de
  l'horaire forecast Open-Meteo (maille ~25 km, donc hors abri).
- **Kc culture** : référentiel ARDEPI Provence (cf.
  ``src/meteo_socle/indices/coefficients_culturaux_ardepi.json``).
  Bilan affiché = cumul pluie vs cumul ET_c sans réserve utile du
  sol — c'est une approximation. Pour le bilan complet
  (sol + réserve + déclenchement irrigation), voir
  ``meteo_socle.indices.bilan_hydrique.calcul_bilan``.
- **Site** : {site["latitude"]:.4f}°N, {site["longitude"]:.4f}°W,
  altitude {site["altitude"]} m, fuseau {site["tz"]}.
- **Cache** : 1 h sur la requête. Rafraîchir = recharger la page.
- **Horizon** : {horizon} jours plafonné par la config.
                """
            )
            st.markdown("**Prévision horaire brute (12 premières heures)** :")
            st.dataframe(prevision.head(12))


if __name__ == "__main__":
    main()
