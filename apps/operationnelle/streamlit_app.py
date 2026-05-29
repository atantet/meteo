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
    figure_bilan_culture,
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

    # ----- Courbes 7 j (vue principale) -----
    st.subheader("Prévision 7 jours — courbes par indicateur")
    st.caption(
        "Pour les T° : courbe pointillée gris = normale OMM 1991-2020. "
        "Zone ombrée rouge = au-dessus de la normale, bleu = en-dessous. "
        "Cliquer sur une figure pour l'agrandir."
    )

    for cfg in COURBES:
        if cfg.colonne not in quotidien.columns:
            continue
        fig = figure_indicateur(quotidien, cfg)
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
