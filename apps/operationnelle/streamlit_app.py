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
    bilan_culture_carry_over,
    bilan_tunnel_carry_over,
    figure_bilan_sol_complet,
    figure_bilan_tunnel,
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
from apps.shared.pictograms import codes_dominants_par_jour  # noqa: E402
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


def _afficher_bande_pictogrammes(
    site: dict, horizon_jours: int, modeles: list[tuple[str, str]]
) -> None:
    """Rend une grille jour × modèle avec les pictos Open-Meteo + libellé.

    Une ligne par jour, deux colonnes modèles (ARPEGE, IFS) +
    une colonne accord (✓ / ⚠). Quand un modèle ne couvre pas un
    jour (ARPEGE > 4j), affiche '—'.
    """
    from apps.shared.pictograms import (
        chemin_icone,
    )
    from apps.shared.pictograms import (
        libelle as libelle_picto,
    )

    tz_loc = site.get("tz", "Europe/Paris")
    resultats: dict[str, list[tuple]] = {}
    for nom_modele, code_modele in modeles:
        try:
            prev = _fetch_prevision(site["latitude"], site["longitude"], horizon_jours, code_modele)
            resultats[nom_modele] = codes_dominants_par_jour(prev, tz_locale=tz_loc)
        except Exception:  # noqa: BLE001
            resultats[nom_modele] = []

    # Unifie les dates couvertes par au moins un modèle.
    jours_tous = sorted({jour for codes in resultats.values() for jour, _ in codes})[:horizon_jours]

    en_tete = st.columns([1.6, 1, 1, 1.4])
    en_tete[0].markdown("**Jour**")
    en_tete[1].markdown(f"**{modeles[0][0]}**")
    en_tete[2].markdown(f"**{modeles[1][0]}**")
    en_tete[3].markdown("**Accord**")

    code_par_jour_modele: dict[str, dict[pd.Timestamp, int]] = {
        nom: dict(codes) for nom, codes in resultats.items()
    }

    for jour in jours_tous:
        row = st.columns([1.6, 1, 1, 1.4])
        row[0].markdown(f"**{jour.strftime('%a %d %b').capitalize()}**")
        codes_jour = []
        for idx, (nom_modele, _) in enumerate(modeles, start=1):
            code = code_par_jour_modele.get(nom_modele, {}).get(jour)
            if code is None:
                row[idx].markdown("—")
                continue
            codes_jour.append(code)
            icon_path = chemin_icone(code)
            if icon_path.exists():
                row[idx].image(str(icon_path), width=48)
                row[idx].caption(libelle_picto(code))
            else:
                row[idx].markdown(libelle_picto(code))
        # Colonne accord.
        if len(codes_jour) == 2 and codes_jour[0] == codes_jour[1]:
            row[3].markdown("✓ accord")
        elif len(codes_jour) == 2:
            row[3].markdown("⚠ divergence")
        else:
            row[3].markdown("—")


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

    # ----- Bande pictogrammes 7 j ARPEGE vs IFS -----
    st.subheader("Tendance 7 jours — ARPEGE vs ECMWF IFS")
    st.caption(
        "Deux modèles en parallèle pour révéler l'accord (confiance haute) "
        "ou le désaccord (incertitude) sur la prévision. ARPEGE Météo-France "
        "(~10 km, 0-4 j fiable) vs ECMWF IFS (~9 km, modèle de référence "
        "mondial, 0-10 j)."
    )
    # Config modèles : liste de dicts {label, modele} → liste de tuples.
    modeles_pictos_cfg = config["source_meteo"].get(
        "modeles_pictogrammes",
        [
            {"label": "ARPEGE", "modele": "meteofrance_arpege_europe"},
            {"label": "ECMWF IFS", "modele": "ecmwf_ifs04"},
        ],
    )
    modeles_pictos = [(m["label"], m["modele"]) for m in modeles_pictos_cfg]
    with st.spinner(f"Récupération {' + '.join(m for m, _ in modeles_pictos)}…"):
        try:
            _afficher_bande_pictogrammes(site, horizon, modeles_pictos)
        except Exception as e:  # noqa: BLE001
            st.warning(f"Pictogrammes indisponibles : {e}")

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

    # ----- Bilan hydrique sol complet (plein air + tunnel) -----
    st.subheader("Bilan hydrique — modèle sol complet")
    st.caption(
        "Itération FAO 56 jour par jour avec carry-over RU : si le déficit "
        "RFU dépasse le seuil, irrigation virtuelle à capacité au champ ; "
        "sinon la RU continue son évolution."
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
        f"Kc culture = **{kc:.2f}** · Référentiel ARDEPI plein champ. "
        f"Sous tunnel, on garde le même Kc et on agit sur l'ET₀ via k_tunnel."
    )

    with st.expander("Paramètres sol (partagés plein air + tunnel)", expanded=False):
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

    if culture not in PROFONDEUR_ENRACINEMENT_TYPIQUE:
        st.info(
            f"La culture « {culture} » n'a pas de profondeur d'enracinement "
            "référencée pour le bilan sol complet. Sélectionner une culture "
            "présente dans `PROFONDEUR_ENRACINEMENT_TYPIQUE`."
        )
    else:
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
                )
                st.pyplot(fig_pa, use_container_width=True)
                pluie_tot = float(bilan_pa["pluie_mm"].sum())
                etm_tot = float(bilan_pa["etm_mm"].sum())
                nb_irrig = int(bilan_pa["irrigation_declenchee"].sum())
                besoin_tot = float(bilan_pa["besoin_irrigation_mm"].sum())
                st.markdown(
                    f"**Synthèse 7 j plein champ** : "
                    f"pluie cumulée {pluie_tot:.1f} mm · "
                    f"ETM {etm_tot:.1f} mm · "
                    f"besoin irrigation total {besoin_tot:.1f} mm · "
                    f"{nb_irrig} déclenchement(s) prévu(s)."
                )
            except KeyError as e:
                st.warning(f"Donnée manquante pour le bilan plein champ ({e}).")

        with tab_tu:
            st.caption(
                "Coefficient k_tunnel : facteur de réduction de l'ET₀ pour "
                "passer du climat extérieur au micro-climat tunnel."
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
                fig_tu = figure_bilan_tunnel(bilan_tu, culture, stade, seuil_irrigation_mm)
                st.pyplot(fig_tu, use_container_width=True)
                etm_tot = float(bilan_tu["etm_tunnel_mm"].sum())
                nb_irrig = int(bilan_tu["irrigation_declenchee"].sum())
                besoin_tot = float(bilan_tu["besoin_irrigation_mm"].sum())
                st.markdown(
                    f"**Synthèse 7 j sous tunnel (k_tunnel = {k_tunnel:.2f})** : "
                    f"ETM cumulée {etm_tot:.1f} mm · "
                    f"besoin irrigation total {besoin_tot:.1f} mm · "
                    f"{nb_irrig} déclenchement(s) prévu(s)."
                )
            except KeyError as e:
                st.warning(f"Donnée manquante pour le bilan tunnel ({e}).")

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
- **Smith mildiou** : indicateur informationnel pour tomate sous
  abri (Smith 1956). Détecte les fenêtres où T_min ≥ 10 °C ET
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
