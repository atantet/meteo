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
from collections.abc import Callable
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
from apps.operationnelle.decisions import (  # noqa: E402
    THEMES_LIBELLES,
    GuideDecision,
    evaluer_decisions,
    grouper_par_theme,
    load_exploitation,
)
from apps.operationnelle.indicateurs import (  # noqa: E402
    calculer_indicateurs_quotidiens,
    jours_complets_seulement,
)
from apps.operationnelle.ui_helpers import (  # noqa: E402
    preparer_table_affichage,
    styler_ligne,
)
from apps.shared.dates_fr import format_date_fr  # noqa: E402
from apps.shared.pictograms import codes_dominants_par_jour  # noqa: E402
from apps.shared.style import (  # noqa: E402
    COULEUR_CHAUD,
    COULEUR_FROID,
    COULEUR_NEUTRE,
    COULEUR_OK,
    COULEUR_PLUIE,
    couleur_niveau,
    unite_html,
)
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
    from apps.shared.pictograms import icone_base64
    from apps.shared.pictograms import libelle as libelle_picto

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
    if not jours_tous:
        st.markdown("_Aucune donnée disponible pour les modèles sélectionnés._")
        return

    code_par_jour_modele: dict[str, dict[pd.Timestamp, int]] = {
        nom: dict(codes) for nom, codes in resultats.items()
    }

    # Tableau HTML transposé : 1 ligne par modèle, 1 colonne par jour.
    # Scroll horizontal automatique sur mobile via overflow-x.
    en_tete = (
        '<tr style="background:#fafafa;">'
        '<th style="padding:6px 8px;text-align:left;color:#34495e;'
        'font-size:13px;position:sticky;left:0;background:#fafafa;">Modèle</th>'
        + "".join(
            f'<th style="padding:6px 8px;text-align:center;font-size:11px;'
            f'color:#888;white-space:nowrap;">{jour.strftime("%a %d %b").capitalize()}</th>'
            for jour in jours_tous
        )
        + "</tr>"
    )

    body = []
    for nom_modele, _ in modeles:
        cellules = [
            '<th style="padding:6px 8px;text-align:left;font-size:13px;'
            'color:#34495e;position:sticky;left:0;background:white;">'
            f"{nom_modele}</th>"
        ]
        for jour in jours_tous:
            code = code_par_jour_modele.get(nom_modele, {}).get(jour)
            if code is None:
                cellules.append('<td style="padding:6px 8px;text-align:center;color:#aaa;">—</td>')
            else:
                uri = icone_base64(code)
                lib = libelle_picto(code)
                cellules.append(
                    '<td style="padding:6px 8px;text-align:center;">'
                    f'<img src="{uri}" alt="{lib}" title="{lib}" '
                    'style="width:42px;height:42px;display:block;margin:0 auto;">'
                    f'<div style="font-size:10px;color:#888;margin-top:2px;'
                    f'white-space:nowrap;">{lib}</div></td>'
                )
        body.append("<tr>" + "".join(cellules) + "</tr>")

    html = (
        '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;'
        'border:1px solid #eee;border-radius:4px;">'
        '<table style="border-collapse:collapse;min-width:100%;'
        'font-family:-apple-system,BlinkMacSystemFont,sans-serif;">'
        + en_tete
        + "".join(body)
        + "</table></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _afficher_grille_variables(quotidien: pd.DataFrame) -> None:
    """Grille variables × jours (transposée, scroll horizontal).

    Une ligne par variable (T° min/moy/max, Pluie+proba, ETP, bilan eau
    du jour, Vent moy/raf, Vent direction), une colonne par jour. Source =
    best_match (= quotidien déjà calculé dans main).
    """
    if quotidien.empty:
        return

    def fmt_t(row) -> str:
        try:
            return (
                f'<span style="color:#2980b9;">{row["t_min_celsius"]:.0f}</span>'
                '<span style="color:#aaa;">/</span>'
                f'<span style="color:#7f8c8d;">{row["t_moy_celsius"]:.0f}</span>'
                '<span style="color:#aaa;">/</span>'
                f'<span style="color:#c0392b;">{row["t_max_celsius"]:.0f}</span>'
            )
        except (KeyError, ValueError):
            return "—"

    def fmt_pluie(row) -> str:
        try:
            mm = row["pluie_24h_mm"]
            proba = row.get("prob_pluie_max_pct", None)
            mm_html = f'<span style="color:#3498db;">{mm:.1f}</span>'
            if pd.isna(proba):
                return mm_html
            return (
                mm_html
                + '<span style="color:#aaa;">/</span>'
                + f'<span style="color:#888;">{proba:.0f}</span>'
            )
        except (KeyError, ValueError):
            return "—"

    def fmt_etp(row) -> str:
        try:
            return f"{row['etp_mm']:.1f}"
        except (KeyError, ValueError):
            return "—"

    def fmt_bilan(row) -> str:
        """Bilan eau du jour = pluie − ETP, colorisé selon signe."""
        try:
            v = row["pluie_24h_mm"] - row["etp_mm"]
            couleur = "#27ae60" if v >= 0 else "#c0392b"
            return f'<span style="color:{couleur};">{v:+.1f}</span>'
        except (KeyError, ValueError):
            return "—"

    def fmt_vent(row) -> str:
        try:
            return (
                f'<span style="color:#16a085;">{row["vent_moy_kmh"]:.0f}</span>'
                '<span style="color:#aaa;">/</span>'
                f'<span style="color:#e67e22;">{row["rafales_max_kmh"]:.0f}</span>'
            )
        except (KeyError, ValueError):
            return "—"

    def fmt_direction(row) -> str:
        card = row.get("direction_vent_cardinal", "")
        if not card or pd.isna(card):
            return "—"
        return str(card)

    lignes = [
        ("T° min/moy/max (°C)", fmt_t),
        ("Pluie mm/proba %", fmt_pluie),
        ("ETP (mm)", fmt_etp),
        ("Bilan eau du jour (mm)", fmt_bilan),
        ("Vent moy/raf (km/h)", fmt_vent),
        ("Vent direction", fmt_direction),
    ]

    en_tete = (
        '<tr style="background:#fafafa;">'
        '<th style="padding:6px 8px;text-align:left;color:#34495e;'
        'font-size:13px;position:sticky;left:0;background:#fafafa;">Indicateur</th>'
        + "".join(
            f'<th style="padding:6px 8px;text-align:center;font-size:11px;'
            f'color:#888;white-space:nowrap;">'
            f"{date.strftime('%a %d %b').capitalize()}</th>"
            for date in quotidien.index
        )
        + "</tr>"
    )

    body = []
    for label, formatter in lignes:
        cellules = [
            '<th style="padding:6px 8px;text-align:left;font-size:12px;'
            'color:#34495e;position:sticky;left:0;background:white;">'
            f"{label}</th>"
        ]
        for _date, row in quotidien.iterrows():
            cellules.append(
                '<td style="padding:6px 8px;text-align:center;font-size:12px;'
                f"font-variant-numeric:tabular-nums;color:#34495e;"
                f'white-space:nowrap;">{formatter(row)}</td>'
            )
        body.append("<tr>" + "".join(cellules) + "</tr>")

    html = (
        '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;'
        'border:1px solid #eee;border-radius:4px;margin-top:8px;">'
        '<table style="border-collapse:collapse;min-width:100%;'
        'font-family:-apple-system,BlinkMacSystemFont,sans-serif;">'
        + en_tete
        + "".join(body)
        + "</table></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


@st.cache_data
def _charger_coefficients_kc() -> dict[str, dict[str, float]]:
    """Charge les coefficients culturaux ARDEPI."""
    with open(KC_JSON_PATH) as f:
        return json.load(f)


# Specs de rendu par colonne pour le tableau jour × indicateur des
# détails de cartes : label affiché, unité, formatter HTML stylé (couleurs
# Wong cohérentes avec l'email Veille).
_SPECS_COLONNES_DETAIL: dict[str, tuple[str, str, Callable[[float], str]]] = {
    "t_min_celsius": (
        "T° min",
        "°C",
        lambda v: f'<span style="color:{COULEUR_FROID};font-weight:700;">{v:.1f}</span>',
    ),
    "t_max_celsius": (
        "T° max",
        "°C",
        lambda v: f'<span style="color:{COULEUR_CHAUD};font-weight:700;">{v:.1f}</span>',
    ),
    "t_moy_celsius": (
        "T° moy",
        "°C",
        lambda v: f'<span style="color:{COULEUR_NEUTRE};font-weight:700;">{v:.1f}</span>',
    ),
    "pluie_24h_mm": (
        "Pluie",
        "mm",
        lambda v: f'<span style="color:{COULEUR_PLUIE};font-weight:700;">{v:.1f}</span>',
    ),
    "etp_mm": (
        "ETP",
        "mm",
        lambda v: f'<span style="font-weight:700;">{v:.1f}</span>',
    ),
    "bilan_eau_jour_mm": (
        "Bilan",
        "mm",
        lambda v: (
            f'<span style="color:{COULEUR_OK if v >= 0 else COULEUR_CHAUD};'
            f'font-weight:700;">{v:+.1f}</span>'
        ),
    ),
}


def _surlignage_actif(surlignage: dict[str, tuple[str, float]], col: str, valeur: float) -> bool:
    """True si ``valeur`` déclenche le surlignage pour cette colonne."""
    if col not in surlignage:
        return False
    op, seuil = surlignage[col]
    if pd.isna(valeur):
        return False
    if op == "≤":
        return valeur <= seuil
    if op == "<":
        return valeur < seuil
    if op == "≥":
        return valeur >= seuil
    if op == ">":
        return valeur > seuil
    return False


def _rendre_tableau_detail(
    df: pd.DataFrame,
    surlignage: dict[str, tuple[str, float]] | None = None,
) -> None:
    """Tableau jour × indicateur stylé (cohérent grille variables).

    Lignes = indicateurs présents dans ``df`` parmi les colonnes
    formattables ; colonnes = dates. Style identique à la grille
    variables affichée plus bas dans l'app (scroll horizontal mobile).

    Si ``surlignage`` fourni, les cellules dont la valeur déclenche le
    seuil sont mises en évidence (fond ambre clair + bordure).
    """
    if df is None or df.empty:
        return
    cols = [c for c in _SPECS_COLONNES_DETAIL if c in df.columns]
    if not cols:
        return
    surlignage = surlignage or {}

    en_tete = (
        '<tr style="background:#fafafa;">'
        '<th style="padding:6px 8px;text-align:left;color:#34495e;'
        'font-size:13px;position:sticky;left:0;background:#fafafa;">Indicateur</th>'
        + "".join(
            f'<th style="padding:6px 8px;text-align:center;font-size:11px;'
            f'color:#888;white-space:nowrap;">'
            f"{d.strftime('%a %d %b').capitalize()}</th>"
            for d in df.index
        )
        + "</tr>"
    )

    style_surligne = "background:#fff3cd;box-shadow:inset 0 0 0 1px #E69F00;font-weight:700;"

    body = []
    for col in cols:
        label, unite, fmt = _SPECS_COLONNES_DETAIL[col]
        cellules = [
            '<th style="padding:6px 8px;text-align:left;font-size:12px;'
            'color:#34495e;position:sticky;left:0;background:white;">'
            f"{label}{unite_html(unite)}</th>"
        ]
        for _date, row in df.iterrows():
            try:
                valeur = row[col]
                contenu = fmt(valeur)
                surligne = _surlignage_actif(surlignage, col, valeur)
            except (KeyError, ValueError, TypeError):
                contenu = "—"
                surligne = False
            extra = style_surligne if surligne else ""
            cellules.append(
                '<td style="padding:6px 8px;text-align:center;font-size:12px;'
                "font-variant-numeric:tabular-nums;color:#34495e;"
                f'white-space:nowrap;{extra}">{contenu}</td>'
            )
        body.append("<tr>" + "".join(cellules) + "</tr>")

    html = (
        '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;'
        "border:1px solid #eee;border-radius:4px;margin-top:8px;"
        'margin-bottom:8px;">'
        '<table style="border-collapse:collapse;min-width:100%;'
        'font-family:-apple-system,BlinkMacSystemFont,sans-serif;">'
        + en_tete
        + "".join(body)
        + "</table></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


_PREFIXE_OVERRIDE = "op_override__"


def _cle_session_param(chemin: str) -> str:
    """Clé canonique session_state (points convertis en ``__`` pour éviter
    tout conflit silencieux avec l'attribute access de Streamlit)."""
    return f"{_PREFIXE_OVERRIDE}{chemin.replace('.', '__')}"


def _chemin_depuis_cle(cle: str) -> str:
    """Inverse de ``_cle_session_param`` : reconstruit le chemin dot."""
    return cle.removeprefix(_PREFIXE_OVERRIDE).replace("__", ".")


def _appliquer_overrides_session(exploitation: dict) -> dict:
    """Construit une exploitation effective en mergeant session_state.

    Pour chaque clé override présente dans ``st.session_state``, écrit
    la valeur au chemin dot correspondant dans une copie profonde de
    l'exploitation.
    """
    from copy import deepcopy

    from apps.operationnelle.decisions import set_chemin

    effective = deepcopy(exploitation)
    for k, v in dict(st.session_state).items():
        if not isinstance(k, str) or not k.startswith(_PREFIXE_OVERRIDE):
            continue
        chemin = _chemin_depuis_cle(k)
        try:
            set_chemin(effective, chemin, v)
        except (KeyError, TypeError):
            continue
    return effective


def _rendre_sliders_guide(guide: GuideDecision, exploitation: dict) -> None:
    """Rend les sliders d'ajustement des seuils du guide.

    Pattern Streamlit canonique : on initialise ``session_state[cle]``
    une fois (depuis l'exploitation effective au premier render), puis
    le slider est créé avec ``key=cle`` uniquement (pas de ``value=``).
    Streamlit lit/écrit alors directement dans session_state, et le
    rerun déclenché par un changement de slider re-calcule les guides
    avec le nouveau seuil au cycle suivant.
    """
    from apps.operationnelle.decisions import get_chemin

    if not guide.parametres_ajustables:
        return
    for p in guide.parametres_ajustables:
        cle = _cle_session_param(p.chemin)
        type_int = p.step >= 1.0
        # Initialise une seule fois depuis l'exploitation effective.
        if cle not in st.session_state:
            try:
                val_initiale = get_chemin(exploitation, p.chemin)
            except (KeyError, TypeError):
                continue
            st.session_state[cle] = int(val_initiale) if type_int else float(val_initiale)
        if type_int:
            st.slider(
                p.label,
                int(p.min_value),
                int(p.max_value),
                step=int(p.step),
                key=cle,
                help=p.aide or None,
            )
        else:
            st.slider(
                p.label,
                float(p.min_value),
                float(p.max_value),
                step=float(p.step),
                key=cle,
                help=p.aide or None,
            )


def _rendre_guide_decision(guide: GuideDecision, exploitation: dict) -> None:
    """Rend un guide : titre stylé + détail dépliable + sliders d'ajustement.

    Les guides inactifs (seuil non franchi) sont affichés en gris,
    avec opacité réduite ; les expanders détail / sliders restent
    accessibles. Un changement de slider rerend la section décisions
    avec les nouveaux seuils, ce qui peut faire basculer un guide
    d'inactif à actif (ou inversement).
    """
    if guide.active:
        couleur_titre = couleur_niveau(guide.niveau)
        opacity = "1.0"
    else:
        couleur_titre = "#8a8a8a"
        opacity = "0.55"

    with st.container(border=True):
        col_picto, col_texte = st.columns([1, 11])
        with col_picto:
            st.markdown(
                f"<div style='font-size:32px;line-height:1;padding-top:4px;"
                f"opacity:{opacity};'>{guide.picto}</div>",
                unsafe_allow_html=True,
            )
        with col_texte:
            st.markdown(
                f"<div style='font-size:16px;font-weight:700;color:{couleur_titre};"
                f"opacity:{opacity};margin-bottom:4px;line-height:1.3;'>"
                f"{guide.titre}</div>",
                unsafe_allow_html=True,
            )
            with st.expander("Détail jour par jour"):
                _rendre_tableau_detail(guide.detail_df, guide.surlignage)
            if guide.parametres_ajustables:
                with st.expander("Ajuster les seuils"):
                    _rendre_sliders_guide(guide, exploitation)


def _afficher_section_decisions(quotidien: pd.DataFrame, site_tz: str) -> None:
    """Section en tête : guides de décision basés sur la prévision 7 j."""
    aide = (
        "Invitations à vérifier sur le terrain, motivées par la météo "
        "prévue à 7 j. Chaque guide expose son détail jour par jour et "
        "permet d'ajuster ses seuils en direct ; les sections météo "
        "complètes et les sources restent consultables plus bas."
    )
    st.markdown(
        '<h3 style="margin:8px 0 8px 0;font-size:20px;color:#2c3e50;">'
        "Guides de décision de la semaine "
        f'<span title="{aide}" style="cursor:help;color:#888;'
        "font-size:15px;font-weight:normal;vertical-align:middle;"
        'margin-left:4px;">ℹ️</span>'
        "</h3>",
        unsafe_allow_html=True,
    )

    try:
        exploitation_base = load_exploitation()
    except FileNotFoundError:
        st.info(
            "Configuration exploitation absente — section guides de décision "
            "désactivée. Créer `config/exploitation.yaml` pour activer."
        )
        return

    exploitation = _appliquer_overrides_session(exploitation_base)
    today = pd.Timestamp.now(tz=site_tz).normalize().tz_localize(None)
    guides = evaluer_decisions(quotidien, exploitation, today)

    if not guides:
        st.info("Aucun guide applicable cette semaine (tout hors saison ou données insuffisantes).")
        return

    nb_actifs = sum(1 for g in guides if g.active)
    accord_actif = "s" if nb_actifs > 1 else ""
    accord_appl = "s" if len(guides) > 1 else ""
    st.caption(
        f"{nb_actifs} guide{accord_actif} actif{accord_actif} "
        f"sur {len(guides)} applicable{accord_appl} cette semaine "
        "(les inactifs sont grisés ; leurs seuils restent ajustables)."
    )

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


def main() -> None:
    config = load_config()
    site = config["site"]
    ui_cfg = config["ui"]

    st.set_page_config(
        page_title=ui_cfg["titre"],
        page_icon="🌦️",
        layout="wide",
    )

    # En-tête aligné sur l'email Veille : titre = fenêtre de prévision
    # en clair, sous-titre = lieu.
    horizon_j = int(config["source_meteo"]["horizon_max_jours"])
    tz_site = site.get("tz", "Europe/Paris")
    maintenant = pd.Timestamp.now(tz="UTC").to_pydatetime()
    debut_loc = pd.Timestamp(maintenant).tz_convert(tz_site).to_pydatetime()
    st.markdown(
        '<h2 style="margin:0 0 4px 0;font-size:24px;color:#2c3e50;">'
        f"Prévision du {format_date_fr(debut_loc)} pour {horizon_j} jours"
        "</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="margin:0 0 12px 0;font-size:13px;color:#888;">'
        "La Petite Claye, Pleine-Fougères"
        "</p>",
        unsafe_allow_html=True,
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

    # ----- Guides de décision de la semaine -----
    _afficher_section_decisions(quotidien, site.get("tz", "Europe/Paris"))

    st.divider()
    st.markdown("### Données météo détaillées")
    st.caption(
        "Vue détaillée de la prévision, des bilans hydriques et des sources. "
        "Utile pour vérifier ce qui motive les guides ci-dessus."
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
            {"label": "ECMWF IFS", "modele": "ecmwf_ifs025"},
        ],
    )
    modeles_pictos = [(m["label"], m["modele"]) for m in modeles_pictos_cfg]
    with st.spinner(f"Récupération {' + '.join(m for m, _ in modeles_pictos)}…"):
        try:
            _afficher_bande_pictogrammes(site, horizon, modeles_pictos)
        except Exception as e:  # noqa: BLE001
            st.warning(f"Pictogrammes indisponibles : {e}")

    # Grille variables détaillées sous les pictos, même structure
    # transposée (variables en lignes, jours en colonnes).
    _afficher_grille_variables(quotidien)

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
