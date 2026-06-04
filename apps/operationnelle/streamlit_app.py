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
from apps.operationnelle.series_temp import (  # noqa: E402
    COURBES_HORAIRES,
    etp_horaire_socle,
    preparer_horaire,
)
from apps.shared.dates_fr import format_date_fr  # noqa: E402
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
from meteo_socle.sources.openmeteo_runs import (  # noqa: E402
    AROME,
    ARPEGE,
    ECMWF,
    ECMWF_HRES,
    VARS_AROME,
    VARS_MONO_MODELE,
    OpenMeteoSingleRuns,
    creneau_run,
    fusionner_priorite,
    runs_du_creneau,
)

KC_JSON_PATH = _SRC / "meteo_socle" / "indices" / "coefficients_culturaux_ardepi.json"

# Modèle Open-Meteo → clé de run dans la table créneau (ADR-0011 D3). ARPEGE
# partage son run avec la Veille ; l'ECMWF de la tendance longue prend le run
# HRES déterministe (00/12Z, ≤240 h), distinct du run ENS court de la proba.
_CLE_RUN_APP2 = {ARPEGE: ARPEGE, ECMWF: ECMWF_HRES}


def _slot_now(now_utc: pd.Timestamp) -> pd.Timestamp:
    """Horodatage canonique du créneau courant (clé de cache stable).

    Cadence fixe 12 h (ADR-0011 D3) : le dashboard montre les mêmes runs que
    l'e-mail Veille du même créneau. On dérive un instant *dans* le créneau
    (06Z le matin, 18Z l'après-midi) pour que le cache `st.cache_data` ne
    change qu'aux bascules de créneau, pas à chaque rechargement.
    """
    creneau, jour = creneau_run(now_utc)
    return jour + pd.Timedelta(hours=6 if creneau == "matin" else 18)


@st.cache_data(ttl=3600)
def _fetch_prevision(
    latitude: float,
    longitude: float,
    horizon_jours: int,
    modele: str,
    slot_now: pd.Timestamp,
    n_jours_passe: int = 0,
) -> pd.DataFrame:
    """Fetch Single Runs pour le créneau de ``slot_now`` (ADR-0011).

    Série mono-modèle = run courant du créneau (futur) + passé stitché de
    ``n_jours_passe`` jours (runs explicites, pas de ``past_days``). ``slot_now``
    (stable dans le créneau) sert de clé de cache → un seul fetch par créneau.
    """
    src = OpenMeteoSingleRuns()
    res = src.obtenir_serie_avec_passe(
        modele,
        _CLE_RUN_APP2[modele],
        latitude,
        longitude,
        horizon_jours,
        slot_now,
        variables=VARS_MONO_MODELE,
        n_jours_passe=n_jours_passe,
    )
    return res.df


@st.cache_data(ttl=3600)
def _fetch_ligne_arome(
    latitude: float,
    longitude: float,
    slot_now: pd.Timestamp,
    _arpege_etendu: pd.DataFrame,
    n_jours_passe: int = 2,
) -> pd.DataFrame:
    """Ligne « AROME » de la grille tendance : cœur AROME + **passé stitché**.

    Comme les lignes ARPEGE/ECMWF, le passé est fait de **runs explicites**
    (``obtenir_serie_avec_passe`` : ``n_jours_passe`` jours de segments 12 h des
    créneaux précédents), pas de ``past_days``. Le rayonnement (qu'AROME ne
    fournit pas) est comblé par l'**ARPEGE étendu déjà fetché** (``_arpege_etendu``,
    passé en argument non hashé pour éviter un double stitch). La **proba**
    d'ensemble est ajoutée avec son passé (``past_days`` : un ensemble n'a pas de
    run épinglable). On clippe la fin à l'horizon AROME (init + 48 h) ; au-delà
    c'est le territoire des lignes ARPEGE/ECMWF. La partie *prévision* reste
    identique à l'e-mail Veille (mêmes runs, même fusion par priorité).
    """
    src = OpenMeteoSingleRuns()
    serie_arome = src.obtenir_serie_avec_passe(
        AROME,
        AROME,
        latitude,
        longitude,
        2,
        slot_now,
        variables=VARS_AROME,
        n_jours_passe=n_jours_passe,
    )
    # AROME cœur prioritaire ; ARPEGE étendu comble le rayonnement (→ ETP) et
    # tout trou, sur passé comme futur.
    fusion = fusionner_priorite([serie_arome.df, _arpege_etendu])
    # forecast_days=3 (et non 2) pour couvrir tout le futur AROME jusqu'à
    # ancre+48 h (l'ensemble part de l'heure réelle, pas de l'init AROME).
    proba = src.obtenir_proba_ensemble(latitude, longitude, 3, past_days=n_jours_passe)
    if proba is not None:
        fusion["probabilite_pluie_pct"] = proba.reindex(fusion.index)
    fin = serie_arome.run_courant + pd.Timedelta(hours=48)
    return fusion.loc[fusion.index < fin]


@st.cache_data(ttl=3600)
def _fetch_cartes_geo():  # noqa: ANN202
    """Cartes Météociel ARPEGE-Europe résumé (4 cibles), cache 1 h."""
    from apps.operationnelle.cartes_geo import recuperer_cartes

    return recuperer_cartes()


def _afficher_section_cartes_geo(tz_locale: str) -> None:
    """Section §3 : 4 cartes ARPEGE-Europe Météociel résumé sur J+1 → J+4.

    Visualisation spatiale du contexte synoptique à court / moyen terme
    (pression au sol + précipitations + nébulosité, mode 7 « Résumé »
    Météociel), complémentaire de la grille tendance §1 (variables
    ponctuelles à Pleine-Fougères).
    """
    from apps.shared.dates_fr import JOURS_FR

    st.markdown(
        '<h3 style="margin:8px 0 8px 0;font-size:20px;color:#2c3e50;">'
        "Cartes géographiques ARPEGE-Europe (résumé)"
        "</h3>",
        unsafe_allow_html=True,
    )
    st.caption(
        "ARPEGE-Europe Météo-France via Météociel, mode 7 « Résumé » "
        "(pression au sol + précipitations + nébulosité). Quatre cibles "
        "à T+24, T+48, T+72, T+96 — vue Europe pour anticiper la "
        "circulation des prochains jours."
    )

    try:
        serie = _fetch_cartes_geo()
    except Exception as e:  # noqa: BLE001
        st.warning(f"Cartes ARPEGE-Europe indisponibles : {e}")
        return

    if serie.nb_disponibles == 0:
        st.info(
            "Aucune carte ARPEGE-Europe récupérable pour le moment "
            "(Météociel n'a peut-être pas encore publié le run en cours)."
        )
        return

    # Légende du run en français, en heure locale.
    run_utc = serie.cartes[0].run_utc
    run_loc = run_utc.tz_convert(tz_locale)
    run_str = (
        f"{JOURS_FR[run_loc.weekday()][:3]}. {run_loc.day:02d}/{run_loc.month:02d} "
        f"{run_loc.hour:02d} h"
    )
    st.caption(f"Run ARPEGE-Europe : {run_str} (heure locale) · cible affichée en heure locale.")

    # Grille 2×2 sur desktop, empilée naturellement sur mobile via columns.
    cols = st.columns(2)
    for idx, carte in enumerate(serie.cartes):
        col = cols[idx % 2]
        with col:
            cible_loc = carte.cible_utc.tz_convert(tz_locale)
            cible_str = (
                f"{JOURS_FR[cible_loc.weekday()][:3]}. {cible_loc.day:02d}/"
                f"{cible_loc.month:02d} {cible_loc.hour:02d} h"
            )
            st.markdown(
                f'<div style="font-size:13px;color:#34495e;font-weight:600;'
                f'margin-top:12px;margin-bottom:4px;">'
                f"T+{carte.echeance_h} h · cible {cible_str}"
                "</div>",
                unsafe_allow_html=True,
            )
            if carte.data_uri:
                st.markdown(
                    f'<img src="{carte.data_uri}" '
                    'style="width:100%;border:1px solid #e8e8e8;border-radius:4px;">',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div style="color:#888;font-size:12px;padding:8px;">'
                    "Carte indisponible pour cette échéance.</div>",
                    unsafe_allow_html=True,
                )


# Couleurs Wong alignées sur le mail Veille (cf. `apps/veille/email.py`).
_T_MIN_COLOR = "#0072B2"  # bleu
_T_MAX_COLOR = "#D55E00"  # orange foncé
_T_MOY_COLOR = "#7f8c8d"  # gris
_PLUIE_COLOR = "#56B4E9"  # bleu clair
_PROBA_COLOR = "#888888"  # gris
_VENT_COLOR = "#009E73"  # vert
_RAFALES_COLOR = "#E69F00"  # jaune-orange
_LABEL_COLOR = "#34495e"  # gris foncé (valeurs)
_LIGNE_LABEL_COLOR = "#555"  # gris (label de ligne)
_FOND_PICTO = "#34495e"  # bandeau sombre derrière les pictos
_FOND_SOUS_LABEL = "#cfd6dc"  # texte sur bandeau sombre

_FLECHE_DIRECTION_VENT = {
    "N": "↓",
    "NE": "↙",
    "E": "←",
    "SE": "↖",
    "S": "↑",
    "SO": "↗",
    "O": "→",
    "NO": "↘",
}


def _unite_inline(texte: str) -> str:
    """Span unité discret (gris clair, plus petit) à coller après une valeur."""
    return f'<span style="color:#aaa;font-weight:400;font-size:11px;">&nbsp;{texte}</span>'


def _fmt_t_cell(cellule, fenetre: str) -> str:
    """Cellule T° : mean / max (jour) ou mean / min (nuit), couleurs Veille."""
    if pd.isna(cellule.t_mean) or pd.isna(cellule.t_extreme):
        return "—"
    couleur_extreme = _T_MAX_COLOR if fenetre == "jour" else _T_MIN_COLOR
    libelle = "max" if fenetre == "jour" else "min"
    return (
        f'<span style="color:{_T_MOY_COLOR};">{cellule.t_mean:.0f}</span>'
        '<span style="color:#aaa;">/</span>'
        f'<span style="color:{couleur_extreme};" title="T° {libelle}">'
        f"{cellule.t_extreme:.0f}</span>"
        f"{_unite_inline('°C')}"
    )


def _fmt_pluie_cell(cellule) -> str:
    """Cellule pluie : cumul mm (par modèle déterministe).

    La **proba** n'est PAS affichée ici : c'est une grandeur d'ensemble
    (ECMWF IFS-ENS), pas une sortie du modèle déterministe de la ligne — elle
    a sa propre ligne « Proba pluie » (cf. ``_ligne_proba``).
    """
    if pd.isna(cellule.pluie_mm):
        return "—"
    return f'<span style="color:{_PLUIE_COLOR};">{cellule.pluie_mm:.1f}</span>' + _unite_inline(
        "mm"
    )


def _fmt_proba_cell(cellule) -> str:
    """Cellule proba pluie (%) — ligne dédiée ECMWF IFS-ENS (P ≥ 1 mm/6 h)."""
    if cellule is None or pd.isna(cellule.prob_pluie_pct):
        return "—"
    proba_int = int(round(cellule.prob_pluie_pct))
    return f'<span style="color:{_PROBA_COLOR};">{proba_int:02d}</span>' + _unite_inline("%")


def _fmt_vent_cell(cellule) -> str:
    """Cellule vent : moy / rafales km/h, couleurs Veille."""
    if pd.isna(cellule.vent_moy_kmh) or pd.isna(cellule.rafales_max_kmh):
        return "—"
    return (
        f'<span style="color:{_VENT_COLOR};">{cellule.vent_moy_kmh:.0f}</span>'
        '<span style="color:#aaa;">/</span>'
        f'<span style="color:{_RAFALES_COLOR};" title="rafales">'
        f"{cellule.rafales_max_kmh:.0f}</span>"
        f"{_unite_inline('km/h')}"
    )


def _fmt_etp_cell(cellule) -> str:
    """Cellule ETP : cumul mm sur la fenêtre (socle FAO Penman-Monteith)."""
    if pd.isna(cellule.etp_mm):
        return "—"
    return f'<span style="color:{_LABEL_COLOR};">{cellule.etp_mm:.1f}</span>{_unite_inline("mm")}'


def _fmt_dir_cell(cellule) -> str:
    """Cellule direction : flèche grande + cardinal discret."""
    if not cellule.direction_cardinal:
        return "—"
    fleche = _FLECHE_DIRECTION_VENT.get(cellule.direction_cardinal, "·")
    return (
        f'<span style="font-size:20px;color:{_LABEL_COLOR};line-height:1;">{fleche}</span>'
        f'<span style="color:#888;font-size:11px;">&nbsp;{cellule.direction_cardinal}</span>'
    )


def _afficher_grille_tendance(
    series: list[tuple[str, pd.DataFrame, pd.Series | None]],
    horizon_jours: int,
    tz_locale: str,
) -> None:
    """Grille tendance : colonnes dédoublées jour/nuit × N j, lignes par variable.

    Format : pour chaque jour civil, deux colonnes côte-à-côte (jour
    puis nuit). Pour chaque variable (picto, T°, pluie, vent, direction,
    ETP), deux sous-lignes empilées (ARPEGE puis ECMWF IFS) — paires de
    modèles regroupées par variable, dans l'esprit de la grille Veille.

    Lignes ECMWF rendues sur un fond légèrement grisé pour mieux
    séparer visuellement les blocs « indicateur » entre eux.

    ``series`` : liste de tuples ``(label, prevision_horaire, etp_horaire)``
    où ``etp_horaire`` est la série ETP socle (mm/h) ou ``None``. Si un
    modèle ne couvre pas un jour (ARPEGE > 4 j), les cellules concernées
    affichent « — » discret.
    """
    from apps.operationnelle.tendances import (
        FENETRE_JOUR,
        FENETRE_NUIT,
        agreger_par_fenetre,
    )
    from apps.shared.dates_fr import JOURS_FR
    from apps.shared.pictograms import icone_base64

    # Fond légèrement grisé pour la 2e sous-ligne (ECMWF) — meilleure
    # séparation des blocs « indicateur » que des traits plus épais.
    fond_modeles = ["white", "#f6f7f9"]

    agreges: list[tuple[str, dict]] = []
    for label, horaire, etp_horaire in series:
        if horaire is None or horaire.empty:
            agreges.append((label, {}))
            continue
        agreges.append(
            (
                label,
                agreger_par_fenetre(horaire, tz_locale, horizon_jours, etp_horaire),
            )
        )

    jours_tous: list[pd.Timestamp] = sorted({jour for _, agg in agreges for (jour, _f) in agg})[
        :horizon_jours
    ]
    if not jours_tous:
        st.markdown("_Aucune donnée disponible pour les modèles sélectionnés._")
        return

    # Pivot archive / prévision : index du 1er jour ≥ aujourd'hui local.
    # Tout ce qui précède est de l'archive du modèle, le reste est de la
    # prévision. On affiche une bordure verticale épaisse à ce pivot et
    # un fond légèrement teinté sur les en-têtes des colonnes archive.
    today_local = pd.Timestamp.now(tz=tz_locale).normalize().tz_localize(None)
    idx_pivot = next(
        (i for i, j in enumerate(jours_tous) if j.tz_localize(None) >= today_local),
        len(jours_tous),
    )
    bordure_pivot = "border-left:3px solid #34495e;"
    fond_th_archive = "#eef2f7"  # bleu-gris léger pour distinguer le passé
    fond_th_prevu = "#fafafa"

    def _date_fr(d: pd.Timestamp) -> str:
        # Forme courte FR : "lun. 02/06" — abréviation 3 lettres + . + date.
        return f"{JOURS_FR[d.weekday()][:3]}. {d.day:02d}/{d.month:02d}"

    # En-tête : 2 colonnes fixes à gauche (Indicateur, Modèle) avec
    # rowspan=2, puis paires Jour/Nuit pour chaque date.
    def _th_date(idx_j: int, jour: pd.Timestamp) -> str:
        bordure = bordure_pivot if idx_j == idx_pivot else "border-left:1px solid #e8e8e8;"
        fond = fond_th_archive if idx_j < idx_pivot else fond_th_prevu
        return (
            '<th colspan="2" style="padding:6px 4px;text-align:center;'
            f"font-size:13px;color:#34495e;font-weight:600;background:{fond};"
            f'{bordure}">'
            f"{_date_fr(jour)}</th>"
        )

    def _th_fenetre(idx_j: int, nom: str, est_premiere: bool) -> str:
        # La 1ʳᵉ fenêtre du jour (Nuit) porte la bordure de séparation
        # entre jours civils (et la bordure pivot si c'est aujourd'hui).
        if est_premiere:
            bordure = bordure_pivot if idx_j == idx_pivot else "border-left:1px solid #e8e8e8;"
        else:
            bordure = ""
        fond = fond_th_archive if idx_j < idx_pivot else fond_th_prevu
        return (
            '<th style="padding:2px 4px;text-align:center;font-size:11px;'
            f'color:#888;font-weight:400;background:{fond};{bordure}">'
            f"{nom}</th>"
        )

    en_tete_dates = (
        '<tr style="background:#fafafa;">'
        '<th rowspan="2" style="padding:6px 8px;text-align:left;color:#34495e;'
        "font-size:13px;font-weight:600;position:sticky;left:0;z-index:3;"
        'background:#fafafa;min-width:110px;">Indicateur</th>'
        '<th rowspan="2" style="padding:6px 8px;text-align:left;color:#34495e;'
        "font-size:13px;font-weight:600;position:sticky;left:110px;z-index:3;"
        "background:#fafafa;min-width:90px;border-right:1px solid #e8e8e8;"
        'box-shadow:1px 0 0 #e8e8e8;">Modèle</th>'
        + "".join(_th_date(idx_j, jour) for idx_j, jour in enumerate(jours_tous))
        + "</tr>"
    )
    en_tete_fenetres = (
        '<tr style="background:#fafafa;">'
        + "".join(
            _th_fenetre(idx_j, "Nuit", est_premiere=True)
            + _th_fenetre(idx_j, "Jour", est_premiere=False)
            for idx_j in range(len(jours_tous))
        )
        + "</tr>"
    )

    def _td_variable(libelle: str, sur_fond_sombre: bool = False) -> str:
        """Cellule 1ère colonne, fusionnée sur les sous-lignes (une par modèle)."""
        col = _FOND_SOUS_LABEL if sur_fond_sombre else _LIGNE_LABEL_COLOR
        bg = _FOND_PICTO if sur_fond_sombre else "white"
        return (
            f'<td rowspan="{len(agreges)}" style="padding:4px 8px;font-size:13px;'
            f"color:{col};font-weight:600;position:sticky;left:0;"
            f'background:{bg};white-space:nowrap;vertical-align:middle;">'
            f"{libelle}</td>"
        )

    def _td_modele(modele: str, bg: str, sur_fond_sombre: bool = False) -> str:
        """Cellule 2e colonne (modèle), une par sous-ligne, sticky elle aussi."""
        col = _FOND_SOUS_LABEL if sur_fond_sombre else "#666"
        return (
            f'<td style="padding:4px 8px;font-size:12px;color:{col};'
            f"background:{bg};white-space:nowrap;position:sticky;left:110px;"
            "z-index:2;border-right:1px solid #e8e8e8;"
            'box-shadow:1px 0 0 #e8e8e8;">'
            f"{modele}</td>"
        )

    def _cellule_vide(bg: str, est_pivot: bool = False) -> str:
        bordure = bordure_pivot if est_pivot else "border-left:1px solid #e8e8e8;"
        return (
            '<td style="padding:4px;text-align:center;color:#ccc;'
            f'font-size:13px;background:{bg};{bordure}">—</td>'
        )

    def _cellule_valeur(html_val: str, bg: str, est_pivot: bool = False) -> str:
        bordure = bordure_pivot if est_pivot else "border-left:1px solid #e8e8e8;"
        return (
            '<td style="padding:4px;text-align:center;'
            "font-variant-numeric:tabular-nums;font-size:13px;"
            f'font-weight:700;color:{_LABEL_COLOR};background:{bg};{bordure}">'
            f"{html_val}</td>"
        )

    # Bordure pivot adaptée au fond sombre du bandeau picto : la
    # couleur `#34495e` se confond avec le fond ; on bascule sur un
    # jaune-orange contrasté (cohérent avec les rafales Veille).
    bordure_pivot_picto = "border-left:3px solid #f2c14e;"

    def _cellule_picto(cellule, est_nuit: bool = False, est_pivot: bool = False) -> str:
        bordure = bordure_pivot_picto if est_pivot else "border-left:1px solid #2c3e50;"
        if cellule is None or cellule.code_picto is None:
            return (
                '<td style="padding:4px;text-align:center;color:#ccc;font-size:13px;'
                f'background:{_FOND_PICTO};{bordure}">—</td>'
            )
        uri = icone_base64(cellule.code_picto, nuit=est_nuit)
        return (
            '<td style="padding:2px 4px;text-align:center;'
            f'background:{_FOND_PICTO};{bordure}">'
            f'<img src="{uri}" alt="{cellule.libelle_picto}" '
            f'title="{cellule.libelle_picto}" '
            'style="width:56px;height:56px;display:block;margin:0 auto;">'
            "</td>"
        )

    def _ligne_variable(
        libelle: str,
        format_fn,
        besoin_fenetre: bool = False,
    ) -> list[str]:
        """Construit 2 lignes (une par modèle) pour une variable.

        La cellule libellé de variable est rendue une seule fois en
        ``rowspan=2`` sur la 1ère sous-ligne ; les 2 sous-lignes portent
        chacune leur cellule modèle. Fond ECMWF (2e sous-ligne) légèrement
        grisé pour mieux délimiter les blocs « indicateur ».
        """
        lignes = []
        for i, (label, agg) in enumerate(agreges):
            bg = fond_modeles[i % len(fond_modeles)]
            cellules: list[str] = []
            if i == 0:
                cellules.append(_td_variable(libelle))
            cellules.append(_td_modele(label, bg))
            for idx_j, jour in enumerate(jours_tous):
                for fenetre_idx, fenetre in enumerate((FENETRE_NUIT, FENETRE_JOUR)):
                    est_pivot = idx_j == idx_pivot and fenetre_idx == 0
                    cellule = agg.get((jour, fenetre))
                    if cellule is None:
                        cellules.append(_cellule_vide(bg, est_pivot=est_pivot))
                    else:
                        val = format_fn(cellule, fenetre) if besoin_fenetre else format_fn(cellule)
                        cellules.append(_cellule_valeur(val, bg, est_pivot=est_pivot))
            lignes.append("<tr>" + "".join(cellules) + "</tr>")
        return lignes

    def _lignes_picto() -> list[str]:
        """Bandeau picto sombre, 2 sous-lignes (une par modèle).

        Pour la cellule « nuit », on passe `est_nuit=True` au rendu picto
        pour utiliser la variante lune Meteocons (clear-night, etc.).
        """
        lignes = []
        for i, (label, agg) in enumerate(agreges):
            cellules: list[str] = []
            if i == 0:
                cellules.append(_td_variable("Météo", sur_fond_sombre=True))
            cellules.append(_td_modele(label, _FOND_PICTO, sur_fond_sombre=True))
            for idx_j, jour in enumerate(jours_tous):
                for fenetre_idx, fenetre in enumerate((FENETRE_NUIT, FENETRE_JOUR)):
                    est_pivot = idx_j == idx_pivot and fenetre_idx == 0
                    cellules.append(
                        _cellule_picto(
                            agg.get((jour, fenetre)),
                            est_nuit=(fenetre == FENETRE_NUIT),
                            est_pivot=est_pivot,
                        )
                    )
            lignes.append(f'<tr style="background:{_FOND_PICTO};">' + "".join(cellules) + "</tr>")
        return lignes

    def _ligne_proba() -> list[str]:
        """Ligne dédiée « Proba pluie » — grandeur d'**ensemble** (ECMWF IFS-ENS).

        Découplée des lignes-modèles déterministes : la proba ne sort d'aucun
        d'eux (ni AROME ni ARPEGE ni l'ECMWF-HRES de la tendance), mais des
        membres IFS-ENS (% au cumul ≥ 1 mm/6 h). Une seule sous-ligne. Source =
        l'agrégat de la fusion App 1 (ligne « AROME ») qui porte la proba.
        """
        agg_proba = next((agg for label, agg in agreges if label == "AROME"), None)
        if not agg_proba:
            return []
        bg = "white"
        label_td = (
            '<td style="padding:4px 8px;font-size:13px;'
            f"color:{_LIGNE_LABEL_COLOR};font-weight:600;position:sticky;left:0;"
            'background:white;white-space:nowrap;vertical-align:middle;">'
            "Proba pluie"
            '<br><span style="font-weight:400;font-size:10px;color:#888;">≥ 1 mm/6 h</span></td>'
        )
        cellules = [label_td, _td_modele("ECMWF IFS-ENS", bg)]
        for idx_j, jour in enumerate(jours_tous):
            for fenetre_idx, fenetre in enumerate((FENETRE_NUIT, FENETRE_JOUR)):
                est_pivot = idx_j == idx_pivot and fenetre_idx == 0
                cellule = agg_proba.get((jour, fenetre))
                if cellule is None or pd.isna(cellule.prob_pluie_pct):
                    cellules.append(_cellule_vide(bg, est_pivot=est_pivot))
                else:
                    cellules.append(
                        _cellule_valeur(_fmt_proba_cell(cellule), bg, est_pivot=est_pivot)
                    )
        return ["<tr>" + "".join(cellules) + "</tr>"]

    corps = (
        _lignes_picto()
        + _ligne_variable("T° moy/extr.", _fmt_t_cell, besoin_fenetre=True)
        + _ligne_variable("Pluie", _fmt_pluie_cell)
        + _ligne_proba()
        + _ligne_variable("Vent moy / raf.", _fmt_vent_cell)
        + _ligne_variable("Vent direction", _fmt_dir_cell)
        + _ligne_variable("ETP cumulée", _fmt_etp_cell)
    )

    # `direction:rtl` sur le container place le scroll horizontal
    # initial à droite (= colonnes futures visibles par défaut) ; faire
    # défiler vers la gauche révèle le passé. La table interne reste en
    # `direction:ltr` pour conserver l'ordre temporel naturel des
    # colonnes (passé → futur de gauche à droite).
    html = (
        '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;'
        'direction:rtl;border:1px solid #e8e8e8;border-radius:4px;">'
        '<table style="border-collapse:collapse;min-width:100%;direction:ltr;'
        'font-family:-apple-system,BlinkMacSystemFont,sans-serif;">'
        + en_tete_dates
        + en_tete_fenetres
        + "".join(corps)
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
    # en clair, sous-titre = lieu. On affiche l'horizon long (7 j) car
    # c'est le plus étendu visible sur le dashboard (tendance + cartes).
    horizon_court = int(config["source_meteo"]["horizon_court_jours"])
    horizon_long = int(config["source_meteo"]["horizon_long_jours"])
    modele_court = config["source_meteo"]["modele_court"]
    modele_long = config["source_meteo"]["modele_long"]
    tz_site = site.get("tz", "Europe/Paris")
    maintenant = pd.Timestamp.now(tz="UTC").to_pydatetime()
    debut_loc = pd.Timestamp(maintenant).tz_convert(tz_site).to_pydatetime()
    st.markdown(
        '<h2 style="margin:0 0 4px 0;font-size:24px;color:#2c3e50;">'
        f"Prévision du {format_date_fr(debut_loc)} pour {horizon_long} jours"
        "</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="margin:0 0 12px 0;font-size:13px;color:#888;">'
        "La Petite Claye, Pleine-Fougères"
        "</p>",
        unsafe_allow_html=True,
    )

    # Fetches Single Runs cachés par créneau (clé = slot_now + modele + horizon
    # + n_jours_passe), runs déterministes (ADR-0011) :
    # - ARPEGE court (4 j) sans passé pour §2 guides + indicateurs quotidiens.
    # - ARPEGE étendu (4 j + 2 j de passé stitché) pour §4 courbes horaires +
    #   §1 tendance étendue. Le passé est fait de runs explicites (stitch des
    #   créneaux précédents), pas de `past_days` — provenance exacte.
    # - ECMWF-HRES long (7 j) pour §1 tendance.
    n_past_days = 2
    now_utc = pd.Timestamp.now(tz="UTC")
    slot_now = _slot_now(now_utc)
    with st.spinner(
        f"Récupération prévisions Single Runs ({modele_court} {horizon_court} j "
        f"+ {modele_long} {horizon_long} j)…"
    ):
        try:
            prevision_courte = _fetch_prevision(
                site["latitude"], site["longitude"], horizon_court, modele_court, slot_now
            )
            prevision_courte_etendue = _fetch_prevision(
                site["latitude"],
                site["longitude"],
                horizon_court,
                modele_court,
                slot_now,
                n_jours_passe=n_past_days,
            )
            prevision_longue = _fetch_prevision(
                site["latitude"],
                site["longitude"],
                horizon_long,
                modele_long,
                slot_now,
                n_jours_passe=n_past_days,
            )
        except Exception as e:  # noqa: BLE001
            st.error(f"Erreur de récupération des prévisions : {e}")
            st.stop()

        # Ligne AROME : cœur AROME + passé stitché (comme ARPEGE/ECMWF),
        # rayonnement comblé par l'ARPEGE étendu, proba avec passé. La prévision
        # reste = e-mail Veille. Dégradation gracieuse : si le run AROME est muet,
        # on l'omet et le dashboard part avec ARPEGE + ECMWF (pas de st.stop()).
        try:
            prevision_arome = _fetch_ligne_arome(
                site["latitude"], site["longitude"], slot_now, prevision_courte_etendue, n_past_days
            )
        except Exception:  # noqa: BLE001
            prevision_arome = None

    quotidien_court = calculer_indicateurs_quotidiens(prevision_courte, config, now_utc=now_utc)
    quotidien_court = jours_complets_seulement(quotidien_court, prevision_courte)

    # ETP socle FAO Penman-Monteith horaire pour ECMWF (la version
    # étendue ARPEGE est calculée juste avant le rendu de la grille
    # tendance). Cohérence avec le principe « calcul scientifique =
    # socle, jamais champ fournisseur ».
    etp_long = etp_horaire_socle(prevision_longue, site)

    # Alias utilisé par les sections séries temporelles + bilan hydrique
    # + sources : court terme (ARPEGE).
    prevision = prevision_courte
    quotidien = quotidien_court

    # ----- §1 Tendance jour/nuit × N j × 3 modèles -----
    st.markdown(
        '<h3 style="margin:8px 0 8px 0;font-size:20px;color:#2c3e50;">'
        f"Tendance {horizon_long} jours — AROME · ARPEGE · ECMWF IFS"
        "</h3>",
        unsafe_allow_html=True,
    )
    # Provenance exacte : init de chaque run servi pour ce créneau (ADR-0011 D3).
    # AROME et ARPEGE partagent le run de la demi-journée ; ECMWF-HRES prend le
    # dernier run long 00/12Z. La proba n'a pas de run épinglable (ensemble).
    _creneau_a2, _jour_a2 = creneau_run(slot_now)
    _runs_a2 = runs_du_creneau(_creneau_a2, _jour_a2)

    def _fmt_run_a2(ts: pd.Timestamp) -> str:
        return ts.strftime("%d/%m %HZ")

    st.caption(
        "Trois modèles en parallèle, deux fenêtres par jour (UTC, alignées sur les "
        "cycles de run) : Nuit (18-06 UTC) puis Jour (06-18 UTC). "
        f"**Runs utilisés (UTC)** — AROME France HD ~1,3 km : {_fmt_run_a2(_runs_a2[AROME])} "
        "(cœur, ± 48 h autour de l'init, identique à l'e-mail Veille) · "
        f"ARPEGE Météo-France ~10 km : {_fmt_run_a2(_runs_a2[ARPEGE])} (0-{horizon_court} j) · "
        f"ECMWF-HRES ~9 km : {_fmt_run_a2(_runs_a2[ECMWF_HRES])} (0-{horizon_long} j, "
        "tendance longue) ; cellules « — » au-delà de l'horizon de chaque modèle. "
        f"Passé ({n_past_days * 24} h) = stitch de runs explicites des créneaux précédents "
        "pour les trois modèles — faire défiler vers la gauche. "
        "Proba pluie : % de membres ECMWF IFS-ENS au cumul ≥ 1 mm/6 h, **dernier run "
        "d'ensemble** (non épinglable ; son passé vient de ce même run)."
    )

    # Frontière passé/prévision = pivot UTC (00Z du jour). Les trois modèles
    # portent le passé stitché (runs explicites) ; AROME est borné à ± 48 h
    # autour de l'init (son horizon), d'où « — » au-delà.
    etp_arpege_etendu = etp_horaire_socle(prevision_courte_etendue, site)
    series_tendance: list[tuple[str, pd.DataFrame, pd.Series | None]] = []
    if prevision_arome is not None and not prevision_arome.empty:
        series_tendance.append(("AROME", prevision_arome, etp_horaire_socle(prevision_arome, site)))
    series_tendance.append(("ARPEGE", prevision_courte_etendue, etp_arpege_etendu))
    series_tendance.append(("ECMWF IFS", prevision_longue, etp_long))
    _afficher_grille_tendance(
        series_tendance,
        horizon_jours=horizon_long + n_past_days,
        tz_locale="UTC",
    )

    # ----- §2 Guides de décision de la semaine (horizon court ARPEGE) -----
    _afficher_section_decisions(quotidien_court, site.get("tz", "Europe/Paris"))

    # ----- §3 Cartes géographiques ECMWF 7 j (Météociel) -----
    _afficher_section_cartes_geo(tz_site)

    st.divider()
    st.markdown(
        '<h3 style="margin:8px 0 8px 0;font-size:20px;color:#2c3e50;">'
        "Séries temporelles détaillées"
        "</h3>",
        unsafe_allow_html=True,
    )

    # ----- Courbes horaires (vue principale, en onglets) -----
    # Source : ARPEGE étendu = N j passés (stitch de runs explicites) +
    # N j de prévision.
    st.markdown(
        '<h4 style="margin:14px 0 4px 0;font-size:15px;color:#34495e;">'
        f"Prévision horaire — {n_past_days * 24} h passées + {horizon_court} j ARPEGE"
        "</h4>",
        unsafe_allow_html=True,
    )
    horaire_courbes = preparer_horaire(prevision_courte_etendue, site)

    # Seuils dynamiques tirés de la config alertes : la courbe T° horaire
    # est unique et traverse les deux régimes (gel et canicule), donc on
    # affiche les deux seuils sur la même courbe.
    alertes_cfg = config["alertes"]
    seuils_t_horaire: list[Seuil] = []
    if alertes_cfg.get("gel", {}).get("actif"):
        seuils_t_horaire.append(
            Seuil(
                float(alertes_cfg["gel"]["seuil_celsius"]),
                f"Seuil gel ({alertes_cfg['gel']['seuil_celsius']:g} °C)",
                "#2980b9",
            )
        )
    if alertes_cfg.get("canicule", {}).get("actif"):
        seuils_t_horaire.append(
            Seuil(
                float(alertes_cfg["canicule"]["seuil_celsius"]),
                f"Seuil canicule ({alertes_cfg['canicule']['seuil_celsius']:g} °C)",
                "#c0392b",
            )
        )
    seuils_par_colonne: dict[str, list[Seuil]] = {"temperature_2m_c": seuils_t_horaire}

    # Bloc 1 — onglets horaires (analyses du modèle + prévision).
    # Pivot = now_utc pour le split visuel analyse / prévision.
    t_pivot_horaire = pd.Timestamp.now(tz="UTC")
    courbes_horaires_dispo = [c for c in COURBES_HORAIRES if c.colonne in horaire_courbes.columns]
    if courbes_horaires_dispo:
        onglets_h = st.tabs([c.titre for c in courbes_horaires_dispo])
        for tab, cfg in zip(onglets_h, courbes_horaires_dispo, strict=False):
            with tab:
                fig = figure_indicateur(
                    horaire_courbes,
                    cfg,
                    figsize=(5.5, 2.5),
                    seuils_extra=seuils_par_colonne.get(cfg.colonne),
                    t_pivot=t_pivot_horaire,
                    legende_externe=True,
                )
                col_plot, _ = st.columns([2, 1])
                with col_plot:
                    st.pyplot(fig, use_container_width=True)

    # ----- Bilan hydrique sol complet (plein air + tunnel) -----
    st.markdown(
        '<h4 style="margin:14px 0 4px 0;font-size:15px;color:#34495e;">'
        "Bilan hydrique — modèle sol complet"
        "</h4>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Itération FAO 56 jour par jour avec carry-over RU : si le déficit "
        "RFU dépasse le seuil, irrigation virtuelle à capacité au champ ; "
        "sinon la RU continue son évolution."
    )

    coefficients = _charger_coefficients_kc()
    cultures = sorted(coefficients.keys())
    # Tomate en défaut (culture sensible de référence sous abri).
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
                    f"**Synthèse 7 j sous tunnel (k_tunnel = {k_tunnel:.2f})** : "
                    f"ETM cumulée {etm_tot:.1f} mm · "
                    f"besoin irrigation total {besoin_tot:.1f} mm · "
                    f"{nb_irrig} déclenchement(s) prévu(s)."
                )
            except KeyError as e:
                st.warning(f"Donnée manquante pour le bilan tunnel ({e}).")

    # ----- Transparence sources (principe #5) -----
    if ui_cfg.get("inclure_sources_brutes", True):
        with st.expander("Vérifier les sources"):
            st.markdown(
                f"""
- **Sources de données** : Open-Meteo (REST, sans authentification),
  deux modèles distincts par échéance :
  - **Court terme** ({horizon_court} j) — guides + séries temp :
    ``{modele_court}`` (ARPEGE Météo-France, ~10 km).
  - **Long terme** ({horizon_long} j) — tendance + cartes : ``{modele_long}``
    (ECMWF IFS, ~9 km, référence mondiale).
- **Analyse modèle ({n_past_days} j passés)** : récupérée via le
  paramètre ``past_days`` d'Open-Meteo Forecast — chaque heure passée
  correspond à la sortie T+0 du run ARPEGE le plus récent qui la
  couvrait (typiquement les analyses 00 Z / 06 Z / 12 Z / 18 Z).
  **Ce ne sont pas des observations directes** ni une vraie réanalyse
  type ERA5 : ce sont les états initiaux du modèle pour ces heures,
  donc cohérents avec la prévision en cours mais sujets à un éventuel
  biais du modèle sur des phénomènes locaux mal capturés. Distingué
  dans les courbes par un trait translucide (« Analyse modèle ») vs
  opaque (« Prévision »).
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
- **Risque maladie** : guide « nuit douce » (T° min journalière ≥ 15 °C).
  Constat météo (PAS un modèle pathogène) — les nuits douces sous abri
  mal aéré favorisent l'activité microbienne (oïdium, botrytis, mildiou…).
  Remplace l'ancien indicateur Smith mildiou (humectation), abandonné.
- **Kc culture** : référentiel ARDEPI Provence (cf.
  ``src/meteo_socle/indices/coefficients_culturaux_ardepi.json``).
  Bilan affiché = cumul pluie vs cumul ET_c sans réserve utile du
  sol — c'est une approximation. Pour le bilan complet
  (sol + réserve + déclenchement irrigation), voir
  ``meteo_socle.indices.bilan_hydrique.calcul_bilan``.
- **Site** : {site["latitude"]:.4f}°N, {site["longitude"]:.4f}°W,
  altitude {site["altitude"]} m, fuseau {site["tz"]}.
- **Cache** : 1 h sur chaque requête (court + long). Rafraîchir = recharger la page.
- **Horizons** : court {horizon_court} j (ARPEGE), long {horizon_long} j (ECMWF).
                """
            )
            st.markdown("**Prévision horaire brute (12 premières heures)** :")
            st.dataframe(prevision.head(12))


if __name__ == "__main__":
    main()
