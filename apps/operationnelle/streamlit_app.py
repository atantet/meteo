"""Vue dashboard Streamlit — App 2 Opérationnelle.

Entry point pour Streamlit Cloud et `streamlit run`.

USAGE
-----

Local :
    streamlit run apps/operationnelle/streamlit_app.py

Streamlit Community Cloud :
    Main file path = ``apps/operationnelle/streamlit_app.py``
"""

from __future__ import annotations

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

from apps.operationnelle.config import load_config  # noqa: E402
from apps.operationnelle.indicateurs import (  # noqa: E402
    calculer_indicateurs_quotidiens,
    jours_complets_seulement,
)
from apps.operationnelle.ui_helpers import (  # noqa: E402
    LIBELLES_COLONNES,
    libelle,
    preparer_table_affichage,
    styler_ligne,
)
from apps.shared.dates_fr import format_horodatage_fr  # noqa: E402
from meteo_socle.sources.openmeteo import OpenMeteoForecast  # noqa: E402


@st.cache_data(ttl=3600)
def _fetch_prevision(
    latitude: float, longitude: float, horizon_jours: int, modele: str
) -> pd.DataFrame:
    """Fetch Open-Meteo, cache 1 h pour limiter les requêtes."""
    src = OpenMeteoForecast(modele=modele)
    return src.obtenir_prevision(latitude, longitude, horizon_jours)


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

    # ----- Vue Semaine -----
    st.subheader("Vue Semaine")
    st.caption(
        "Coloration : T° rouge si gel/canicule franchi · "
        "rafales orange si vent fort · pluie bleu si intense."
    )
    table = preparer_table_affichage(quotidien, tz=site["tz"])
    styler = table.style.apply(lambda row: styler_ligne(row, config["alertes"]), axis=1)
    st.dataframe(styler, use_container_width=True)

    # ----- Courbes par indice -----
    st.subheader("Courbes par indicateur")
    cols = list(LIBELLES_COLONNES.keys())
    onglets = st.tabs([libelle(c) for c in cols])
    for tab, col in zip(onglets, cols, strict=False):
        with tab:
            st.line_chart(quotidien[col])

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
- **Normale T° (1991-2020 OMM)** : extraite de
  ``data/climato/normale_jour_lapetiteclaye.csv`` (ERA5 30 ans —
  voir `scripts/compute_normale_jour.py`). Colonne "Écart normale"
  = T° moy du jour − normale T° pour ce jour-de-l'année.
- **Direction dominante** : moyenne vectorielle horaire pondérée
  par la vitesse.
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
