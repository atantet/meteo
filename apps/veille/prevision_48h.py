"""Assemblage de la prévision 48 h d'App 1 depuis le portail-api (ADR-0021).

Réunit les sources socle « directes » (clé DP / ECMWF, joignables depuis CI) en
un objet **compatible avec le pipeline existant** (mêmes colonnes socle que
``PrevisionMF.df``), en remplacement du webservice bloqué :

- **AROME HD** (``meteofrance_arome``) → T/HR/vent/pluie + champs picto ;
- **picto dérivé** (``temps_sensible.serie_code_temps_mf``) → ``weather_code``,
  phase ← type de précip MF, brouillard ← visibilité, **sans orage** ;
- **PE-AROME** (``meteofrance_proba_arome``) → ``probabilite_pluie_pct`` ;
- **DPVigilance** (``dpvigilance``) → overlay **orage** sur le picto (doctrine
  « une seule méthode » : l'orage vient de la Vigilance, horodaté).

Le cœur ``assembler_df_48h`` est **pur** (entrées déjà fetchées) → testable hors
réseau ; ``assembler_prevision_48h`` orchestre les fetchs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
import requests

from meteo_socle.indices.temps_sensible import serie_code_temps_mf
from meteo_socle.sources.dpvigilance import (
    TrancheVigilance,
    VigilanceDepartementDP,
    VigilanceDPIndisponibleError,
    recuperer_vigilance_dp,
)
from meteo_socle.sources.meteofrance_arome import MeteoFranceArome
from meteo_socle.sources.meteofrance_proba_arome import MeteoFranceProbaArome

logger = logging.getLogger(__name__)

#: Code OMM 4677 de l'orage par défaut (overlay Vigilance, niveau inconnu).
WMO_ORAGE = 95
#: Code OMM par niveau de Vigilance orages (jaune→91, orange→92, rouge→93).
#: Permite d'afficher l'icône la mieux adaptée (averses orageuses légères/fortes).
_WMO_ORAGE_PAR_NIVEAU: dict[int, int] = {2: 91, 3: 92, 4: 93}
#: Codes ciel « dégagé » (OMM) qui SUPPRIMENT l'overlay orage : 0 ensoleillé, 1 peu
#: nuageux. Au-dessus (≥ 2 partiellement nuageux, ou précip ≥ 45) **ou** ciel inconnu
#: (``<NA>``), on peint l'orage Vigilance. Ciel dégagé → pas le moment du coup de
#: tonnerre ; le risque orage reste porté par le tableau Vigilance.
CODES_CIEL_DEGAGE = (0, 1)
#: Tolérance d'appariement proba (échéances PE-AROME) ↔ heures AROME.
_TOL_PROBA = pd.Timedelta(hours=3)


@dataclass
class Prevision48h:
    """Prévision 48 h assemblée, surface compatible avec ``PrevisionMF``.

    ``df`` : horaire UTC, colonnes socle + ``weather_code`` + ``probabilite_pluie_pct``.
    ``proba_bins`` : proba PE-AROME (6 h) pour la semaine (``proba_max_par_fenetre``).
    """

    df: pd.DataFrame
    proba_bins: pd.Series
    updated_on: pd.Timestamp
    position: dict  # {"name": commune, "timezone": tz} — forme attendue par composer_email


def _proba_horaire(proba_fenetre: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Diffuse la proba (échéances PE-AROME) sur l'index horaire AROME (plus proche)."""
    if proba_fenetre.empty:
        return pd.Series(float("nan"), index=index, name="probabilite_pluie_pct")
    s = proba_fenetre.reindex(index, method="nearest", tolerance=_TOL_PROBA)
    s.name = "probabilite_pluie_pct"
    return s


def assembler_df_48h(
    arome_df: pd.DataFrame,
    proba_6h: pd.Series,
    tranches_orages: list[TrancheVigilance],
) -> pd.DataFrame:
    """Cœur pur : df AROME + ``weather_code`` (picto MF) + proba + overlay orage.

    Le picto est dérivé **sans orage** (doctrine) ; on superpose ensuite le code
    orage (95) sur les heures couvertes par une **tranche de Vigilance orages**
    (horodatée, dept) — **mais seulement si le ciel modèle n'est pas dégagé** à cette
    heure (nébulosité ≥ partiellement nuageux). Une nuit étoilée dans la fenêtre
    Vigilance ne porte pas l'orage à cet instant ; on se cale ainsi sur le picto MF
    par créneau (vérifié 2026-06-22 : MF affiche peu nuageux les heures dégagées,
    orage les heures nuageuses), le **risque** restant porté par le tableau Vigilance.
    ``code_dominant_fenetre`` fait ressortir l'orage sur la fenêtre 6 h chevauchée.
    """
    df = arome_df.copy()
    df["weather_code"] = serie_code_temps_mf(df)
    df["probabilite_pluie_pct"] = _proba_horaire(proba_6h, df.index)
    for tr in tranches_orages:
        wmo_tr = _WMO_ORAGE_PAR_NIVEAU.get(tr.niveau, WMO_ORAGE)
        dans_tranche = (df.index >= tr.debut) & (df.index < tr.fin)
        # Garde-fou ciel : pas d'orage sur une heure au ciel CONFIRMÉ dégagé (0/1). Les
        # heures nuageuses (≥ 2), pluvieuses (≥ 45) ou au ciel inconnu (<NA>) gardent
        # l'overlay. ``isin`` renvoie False sur <NA> → masque booléen propre (pas de NA).
        masque = dans_tranche & ~df["weather_code"].isin(CODES_CIEL_DEGAGE)
        df.loc[masque, "weather_code"] = wmo_tr
    return df


def assembler_prevision_48h(
    run_utc: pd.Timestamp,
    latitude: float,
    longitude: float,
    departement: str,
    position: dict,
    run_proba_utc: pd.Timestamp | None = None,
    basic: str | None = None,
    session: requests.Session | None = None,
    cache_dir: str | None = None,
) -> tuple[Prevision48h, VigilanceDepartementDP | None]:
    """Fetch AROME + PE-AROME + DPVigilance et assemble la 48 h + la Vigilance.

    ``run_proba_utc`` : run PE-AROME (cycle propre) ; défaut = ``run_utc``. AROME et
    PE-AROME lèvent leurs ``*IndisponibleError`` (cascade gérée par l'appelant, qui
    peut replier sur un run plus ancien). **DPVigilance est tolérée** : si elle échoue,
    la 48 h est quand même produite (sans overlay orage), Vigilance à ``None`` — un
    bandeau Vigilance manquant ne doit pas faire sauter toute la 48 h.
    """
    session = session or requests.Session()
    arome = MeteoFranceArome(basic=basic, session=session).obtenir_run(
        run_utc, latitude, longitude, horizon_jours=2, cache_dir=cache_dir
    )
    proba_6h = MeteoFranceProbaArome(basic=basic, session=session).obtenir_proba(
        run_proba_utc or run_utc, latitude, longitude, horizon_jours=2, fenetre_h=6, seuil_mm=1
    )
    vigilance: VigilanceDepartementDP | None
    try:
        vig = recuperer_vigilance_dp(departement, basic=basic, session=session)
        tranches = vig.tranches_orages()
        vigilance = vig
    except VigilanceDPIndisponibleError as e:
        logger.warning("DPVigilance indisponible (%s) → 48 h sans overlay orage.", e)
        vigilance, tranches = None, []
    df = assembler_df_48h(arome, proba_6h, tranches)
    prevision = Prevision48h(df=df, proba_bins=proba_6h, updated_on=run_utc, position=position)
    return prevision, vigilance
