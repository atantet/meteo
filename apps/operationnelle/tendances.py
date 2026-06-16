"""Tendance jour/nuit × N j × 2 modèles pour le dashboard App 2.

Agrège une prévision horaire Open-Meteo en cellules « fenêtre × jour »,
chaque cellule portant les variables agrégées attendues par la grille
de tendance :

- ``t_mean`` et ``t_extreme`` (T_max pour la fenêtre « jour », T_min pour
  la fenêtre « nuit »)
- ``pluie_mm`` (cumul de la fenêtre)
- ``prob_pluie_pct`` (proba pluie de la fenêtre — **signal indépendant des
  modèles** injecté par l'appelant via ``proba_par_fenetre``, cf.
  ``proba_max_par_fenetre`` ; le df modèle ne la porte pas)
- ``vent_moy_kmh`` (moyenne sur la fenêtre, conversion m/s → km/h)
- ``rafales_max_kmh`` (max de la fenêtre)
- ``direction_cardinal`` (vecteur moyen pondéré vitesse, en secteur 8)

Vu côté UI, deux modèles (ARPEGE court terme + ECMWF moyen terme) sont
empilés ; pour chaque jour civil deux colonnes côte-à-côte : Nuit J puis
Jour J (ordre chronologique en partant de minuit).

Convention « jour » / « nuit » :
- ``jour`` : heures locales [FENETRE_JOUR_DEBUT, FENETRE_JOUR_FIN)
- ``nuit`` : **nuit contiguë** = soirée de la veille [FENETRE_JOUR_FIN, 24)
  du jour civil J-1 + matinée [0, FENETRE_JOUR_DEBUT) du jour J.

La nuit J est donc la vraie nuit calendaire qui *précède* le jour J
(elle « mène » au jour J). En partant de minuit on rencontre d'abord la
fin de cette nuit (la matinée), d'où l'ordre d'affichage Nuit J puis
Jour J. La soirée [19, 24) d'un jour est rattachée à la nuit du
lendemain ; pour qu'une nuit soit complète il faut donc disposer de la
soirée de la veille dans la prévision (assurée par ``past_days`` côté
appelant). À la toute première date couverte la soirée J-1 manque : la
nuit n'a alors que sa matinée (cellule partielle, bord gauche de la
grille).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Fenêtre jour : 6 h ≤ h < 18 h UTC (12 h). Le reste est « nuit » (18-06 UTC).
# ADR-0011 D5 : tout en UTC, aligné sur les cycles de run (l'appelant passe
# tz_locale="UTC" pour binner sur l'heure UTC).
FENETRE_JOUR_DEBUT = 6
FENETRE_JOUR_FIN = 18

FENETRE_JOUR = "jour"
FENETRE_NUIT = "nuit"

# Conversion vent : Open-Meteo livre en m/s (cf. socle), grille affiche km/h.
MS_VERS_KMH = 3.6

# Conversion T° : socle Open-Meteo stocke en K (+ 273.15 à l'ingestion,
# cf. `meteo_socle.sources.openmeteo`). La grille affiche en °C.
KELVIN_VERS_CELSIUS = 273.15

# Nombre minimal d'heures couvertes par fenêtre pour créer une cellule.
# Évite l'effet "1 heure de couverture" en fin d'horizon ARPEGE (où le
# décalage UTC fait déborder 1 ou 2 heures sur un jour local supplémentaire,
# affichées comme une cellule complète tout en n'étant pas représentatives).
MIN_HEURES_PAR_FENETRE = 4

# Secteurs cardinaux 8 directions (N, NE, E, SE, S, SO, O, NO).
_CARDINAUX = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


@dataclass(frozen=True)
class CelluleFenetre:
    """Variables agrégées sur une fenêtre (jour OU nuit) d'un jour civil.

    Pas de pictogramme (ADR-0014 D2 : l'App 2 compare les modèles en
    quantitatif ; le verdict illustré est l'affaire de l'App 1).
    """

    t_mean: float
    t_extreme: float  # t_max si « jour », t_min si « nuit »
    pluie_mm: float
    prob_pluie_pct: float
    vent_moy_kmh: float
    rafales_max_kmh: float
    direction_cardinal: str
    direction_deg: float
    etp_mm: float  # cumul ETP socle FAO sur la fenêtre, NaN si non fourni
    nebulosite_pct: float  # nébulosité moyenne sur la fenêtre (%, NaN si absente)
    # Code WMO dominant (sévérité max) de la fenêtre, si le df portait une colonne
    # ``weather_code`` (picto diagnostic unifié, ADR-0021) ; sinon None → le rendu
    # retombe sur le picto nébulosité+pluie historique.
    weather_code: int | None = None


def _direction_cardinal(deg: float) -> str:
    """Convertit un cap (degrés, 0=N, sens horaire) en secteur cardinal 8."""
    if pd.isna(deg):
        return ""
    idx = int(round((deg % 360) / 45)) % 8
    return _CARDINAUX[idx]


def _direction_moyenne_ponderee(group: pd.DataFrame) -> float:
    """Moyenne vectorielle pondérée par la vitesse (cap dominant en degrés).

    Convention météo : les angles sont les *caps d'origine* du vent (0 = N
    venant du nord). On somme les vecteurs (-sin θ, -cos θ) pondérés par
    la vitesse, puis on reprojette en angle. Sans vitesse, poids unitaire.
    """
    if "direction_vent_deg" not in group.columns or group.empty:
        return float("nan")
    s = group["direction_vent_deg"].dropna()
    if s.empty:
        return float("nan")
    rad = np.deg2rad(s)
    if "vitesse_vent_10m" in group.columns:
        poids = group.loc[s.index, "vitesse_vent_10m"].fillna(0.0)
    else:
        poids = pd.Series(1.0, index=s.index)
    u = -poids * np.sin(rad)
    v = -poids * np.cos(rad)
    return float(np.rad2deg(np.arctan2(-u.mean(), -v.mean())) % 360)


def _masque_fenetre(index: pd.DatetimeIndex, jour: pd.Timestamp, fenetre: str) -> np.ndarray:
    """Masque booléen pour la fenêtre demandée sur le jour civil ``jour``.

    ``index`` doit être tz-aware sur la zone locale (heures lues directement).
    ``jour`` est attendu à minuit local, même tz que ``index``.

    « jour » = [DEBUT, FIN) du jour civil J. « nuit » = nuit contiguë qui
    précède J : soirée [FIN, 24) de la veille J-1 + matinée [0, DEBUT) de J.
    Le jour précédent est calculé avec ``DateOffset(days=1)`` (et non
    ``Timedelta``) pour rester correct au passage à l'heure : retrancher
    24 h à un minuit tomberait sur 23 h ou 01 h les jours de bascule DST.
    """
    jours_norm = index.normalize()
    heure = np.asarray(index.hour)
    if fenetre == FENETRE_JOUR:
        est_jour = np.asarray(jours_norm == jour)
        plage = (heure >= FENETRE_JOUR_DEBUT) & (heure < FENETRE_JOUR_FIN)
        return est_jour & plage
    veille = jour - pd.DateOffset(days=1)
    soir_veille = np.asarray(jours_norm == veille) & (heure >= FENETRE_JOUR_FIN)
    matin = np.asarray(jours_norm == jour) & (heure < FENETRE_JOUR_DEBUT)
    return soir_veille | matin


def _bornes_fenetre(jour: pd.Timestamp, fenetre: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Bornes ``[début, fin)`` de la fenêtre (même tz que ``jour``).

    ``jour`` = [DEBUT, FIN) du jour J ; ``nuit`` = [FIN de J-1, DEBUT de J).
    Sert à juger si les données couvrent toute l'étendue de la fenêtre.
    """
    if fenetre == FENETRE_JOUR:
        return (
            jour + pd.Timedelta(hours=FENETRE_JOUR_DEBUT),
            jour + pd.Timedelta(hours=FENETRE_JOUR_FIN),
        )
    veille = jour - pd.DateOffset(days=1)
    return (
        veille + pd.Timedelta(hours=FENETRE_JOUR_FIN),
        jour + pd.Timedelta(hours=FENETRE_JOUR_DEBUT),
    )


def _agreger_cellule(
    group: pd.DataFrame,
    fenetre: str,
    etp_fenetre: pd.Series | None = None,
    prob_pluie_pct: float = float("nan"),
) -> CelluleFenetre:
    """Agrège un sous-DataFrame horaire (déjà filtré sur une fenêtre).

    La T° est convertie K → °C : la socle Open-Meteo stocke en kelvin
    (+ 273.15 à l'ingestion), mais l'utilisateur lit des °C.
    ``etp_fenetre`` est une série ETP horaire (mm/h) déjà filtrée sur
    la même fenêtre ; sa somme donne l'ETP cumulée de la fenêtre.
    ``prob_pluie_pct`` est la proba pluie de la fenêtre — un **signal
    indépendant des modèles** (proba officielle MF), fourni par
    l'appelant, et **non** agrégé depuis une colonne du df (le df ne porte
    que des champs modèle).
    """
    t_k = group.get("temperature_2m")
    t_c = (t_k - KELVIN_VERS_CELSIUS) if t_k is not None else None
    t_mean = float(t_c.mean()) if t_c is not None and not t_c.empty else float("nan")
    if fenetre == FENETRE_JOUR:
        t_extreme = float(t_c.max()) if t_c is not None and not t_c.empty else float("nan")
    else:
        t_extreme = float(t_c.min()) if t_c is not None and not t_c.empty else float("nan")

    pluie_mm = (
        float(group["precipitation"].sum()) if "precipitation" in group.columns else float("nan")
    )

    vent_ms = group.get("vitesse_vent_10m")
    vent_moy_kmh = (
        float(vent_ms.mean() * MS_VERS_KMH)
        if vent_ms is not None and not vent_ms.dropna().empty
        else float("nan")
    )
    raf_ms = group.get("rafales_vent_10m")
    rafales_max_kmh = (
        float(raf_ms.max() * MS_VERS_KMH)
        if raf_ms is not None and not raf_ms.dropna().empty
        else float("nan")
    )

    direction_deg = _direction_moyenne_ponderee(group)

    etp_mm = (
        float(etp_fenetre.dropna().sum())
        if etp_fenetre is not None and not etp_fenetre.dropna().empty
        else float("nan")
    )

    # Nébulosité : socle en fraction 0-1 → moyenne sur la fenêtre, affichée en %.
    neb = group.get("cloud_cover")
    nebulosite_pct = (
        float(neb.mean() * 100.0) if neb is not None and not neb.dropna().empty else float("nan")
    )

    # Picto unifié (ADR-0021) : si le df porte un ``weather_code`` horaire (dérivé par
    # le moteur diagnostic), on prend le code **dominant** (sévérité max) de la fenêtre
    # — même agrégation que la grille 48 h. Sinon None (rendu nébulosité+pluie).
    weather_code: int | None = None
    if "weather_code" in group.columns:
        from apps.shared.pictograms import code_dominant_fenetre

        weather_code = code_dominant_fenetre(group["weather_code"])

    return CelluleFenetre(
        t_mean=t_mean,
        t_extreme=t_extreme,
        pluie_mm=pluie_mm,
        prob_pluie_pct=prob_pluie_pct,
        vent_moy_kmh=vent_moy_kmh,
        rafales_max_kmh=rafales_max_kmh,
        direction_cardinal=_direction_cardinal(direction_deg),
        direction_deg=direction_deg,
        etp_mm=etp_mm,
        nebulosite_pct=nebulosite_pct,
        weather_code=weather_code,
    )


def agreger_par_fenetre(
    horaire: pd.DataFrame,
    tz_locale: str = "Europe/Paris",
    horizon_jours: int | None = None,
    etp_horaire: pd.Series | None = None,
    proba_par_fenetre: dict[tuple[pd.Timestamp, str], float] | None = None,
) -> dict[tuple[pd.Timestamp, str], CelluleFenetre]:
    """Agrège la prévision horaire en cellules (date locale, fenêtre).

    Parameters
    ----------
    horaire :
        DataFrame indexé tz-aware UTC, colonnes selon les conventions
        socle (cf. ``OpenMeteoForecast``).
    tz_locale :
        Fuseau de présentation (par défaut Europe/Paris).
    horizon_jours :
        Si fourni, plafonne au nombre de jours locaux couverts.
    etp_horaire :
        Série ETP horaire (mm/h) socle FAO calculée en amont, indexée
        tz-aware UTC. Si fournie, chaque cellule porte la somme ETP de
        sa fenêtre ; sinon `etp_mm` reste à NaN.
    proba_par_fenetre :
        Proba pluie (%) par clé ``(jour_local_minuit, fenetre)`` — un
        **signal indépendant des modèles** (proba officielle MF, cf.
        ``proba_max_par_fenetre``). Chaque cellule prend la valeur de sa
        clé ; absente → NaN. Le df ``horaire`` ne porte **pas** la proba
        (uniquement des champs modèle).

    Returns
    -------
    dict
        Clé = ``(jour_local_minuit, fenetre)`` où ``fenetre`` ∈
        {"jour", "nuit"} ; valeur = ``CelluleFenetre`` agrégée.
        Les fenêtres couvertes par moins de
        ``MIN_HEURES_PAR_FENETRE`` heures sont écartées pour éviter
        l'affichage de cellules peu représentatives.
    """
    if horaire.empty:
        return {}

    df = horaire.copy()
    df.index = pd.DatetimeIndex(df.index).tz_convert(tz_locale)
    # Cast float sur toutes les colonnes numériques : un `pd.concat`
    # entre ERA5 et forecast (toggle « 48 h passées ») peut produire
    # des dtypes `object` quand les colonnes diffèrent entre les
    # morceaux, ce qui fait ensuite échouer `np.deg2rad`, `np.exp`,
    # etc. avec « loop of ufunc does not support argument 0 of type
    # int/float ». `weather_code` reste tel quel (catégoriel int).
    for col in df.columns:
        if col == "weather_code":
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce")

    etp_loc = None
    if etp_horaire is not None and not etp_horaire.empty:
        etp_loc = pd.to_numeric(etp_horaire, errors="coerce").copy()
        etp_loc.index = pd.DatetimeIndex(etp_loc.index).tz_convert(tz_locale)

    jours_uniques = pd.DatetimeIndex(df.index).normalize().unique().sort_values()
    if horizon_jours is not None:
        jours_uniques = jours_uniques[:horizon_jours]

    # Pas natif (le plus grossier) : ARPEGE = 1 h puis 3 h ; ECMWF jusqu'à 6 h.
    # Sert de tolérance de bord pour juger une fenêtre « complète ».
    diffs = pd.Series(df.index).diff().dropna()
    pas = diffs.max() if not diffs.empty else pd.Timedelta(hours=1)

    cellules: dict[tuple[pd.Timestamp, str], CelluleFenetre] = {}
    for jour in jours_uniques:
        for fenetre in (FENETRE_JOUR, FENETRE_NUIT):
            masque = _masque_fenetre(df.index, jour, fenetre)
            if int(masque.sum()) < MIN_HEURES_PAR_FENETRE:
                continue
            # JAMAIS de fausse valeur : on n'agrège (max/min/cumul) que si les
            # données couvrent **toute l'étendue** de la fenêtre, aux deux bords
            # (à un pas natif près). Une fenêtre tronquée — run partiellement
            # publié, trou d'ingestion — est écartée plutôt que de produire un
            # extrême ou un cumul faux (ex. max matinal pris pour max du jour).
            debut, fin = _bornes_fenetre(jour, fenetre)
            couverts = df.index[masque]
            if couverts.min() > debut + pas or couverts.max() < fin - pas:
                continue
            etp_fenetre = None
            if etp_loc is not None:
                masque_etp = _masque_fenetre(etp_loc.index, jour, fenetre)
                etp_fenetre = etp_loc.loc[masque_etp]
            prob = (
                proba_par_fenetre.get((jour, fenetre), float("nan"))
                if proba_par_fenetre is not None
                else float("nan")
            )
            cellules[(jour, fenetre)] = _agreger_cellule(df.loc[masque], fenetre, etp_fenetre, prob)

    return cellules


def proba_max_par_fenetre(
    proba_bins: pd.Series | None,
    tz_locale: str = "Europe/Paris",
    horizon_jours: int | None = None,
) -> dict[tuple[pd.Timestamp, str], float]:
    """Proba pluie **max** par fenêtre (jour/nuit), depuis des bins MF.

    ``proba_bins`` : série indexée tz-aware UTC sur le **début de chaque bin**
    de la proba officielle MF (3 h près de l'échéance, puis 6 h ; bins alignés
    minuit UTC), valeur = proba pluie (%). C'est un **signal indépendant des
    modèles** : on l'agrège ici par la **même** logique de fenêtre que
    ``agreger_par_fenetre`` (``_masque_fenetre``), puis l'appelant l'injecte
    dans les cellules via ``proba_par_fenetre``.

    Les bins (≤ 6 h, alignés minuit) tombent **entièrement** dans une fenêtre
    de 12 h (Jour [06, 18) / Nuit [18, 06) en UTC) → la proba de la fenêtre est
    le ``max`` des bins qu'elle contient (cf. ECMWF FUG ; aucune granularité
    horaire n'est nécessaire, le ``max`` est invariant par densification).

    Renvoie ``{(jour_local_minuit, fenetre): proba_pct}``. Bins vides → ``{}``.
    """
    if proba_bins is None or proba_bins.dropna().empty:
        return {}
    s = pd.to_numeric(proba_bins, errors="coerce").dropna()
    s.index = pd.DatetimeIndex(s.index).tz_convert(tz_locale)
    jours = pd.DatetimeIndex(s.index).normalize().unique().sort_values()
    if horizon_jours is not None:
        jours = jours[:horizon_jours]
    out: dict[tuple[pd.Timestamp, str], float] = {}
    for jour in jours:
        for fenetre in (FENETRE_JOUR, FENETRE_NUIT):
            masque = _masque_fenetre(s.index, jour, fenetre)
            vals = s.loc[masque]
            if not vals.empty:
                out[(jour, fenetre)] = float(vals.max())
    return out
