"""Client Hub'Eau piézométrie — niveau de nappe (proxy de tendance).

Récupère la chronique de niveau d'un piézomètre ADES via l'API publique
Hub'Eau et en dérive un **état de la nappe** : niveau le plus récent,
position dans la distribution **saisonnière** historique (percentile du
mois courant), tendance récente, et plus-bas historique de référence.

Cas d'usage : bulletin mensuel « état de la ressource en eau ». Le
piézomètre du Calvaire à Bonnemain (``02465X0061/F``) est un **proxy de
tendance régionale** de la nappe de socle — *pas* le débit du forage de
l'exploitation (unité de socle voisine, aquifère compartimenté, aucune
corrélation mesurée). À présenter comme tel.

Endpoint :
- ``GET /api/v1/niveaux_nappes/chroniques?code_bss=<bss>`` — chronique de
  niveaux validés (``niveau_nappe_eau`` en m NGF, ``profondeur_nappe`` en m
  sous le sol, ``date_mesure``).

Dégradation gracieuse : toute erreur réseau/format renvoie ``None`` (le
bloc nappe est alors omis du bulletin).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
import requests

from ._http_retry import get_avec_retry

logger = logging.getLogger(__name__)

CHRONIQUES_URL = "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/chroniques"

# Piézomètre du Calvaire à Bonnemain (35) — proxy de tendance pour le
# secteur du forage de La Petite Claye (masse d'eau souterraine FRGG123).
CODE_BSS_BONNEMAIN = "02465X0061/F"

# Bornes de classification de la position saisonnière (percentile du mois).
SEUIL_PERCENTILE_BAS = 25
SEUIL_PERCENTILE_HAUT = 75

# Taille de page (la chronique de Bonnemain ~ 7700 points sur 21 ans).
_TAILLE_PAGE = 20000


@dataclass(frozen=True)
class EtatNappe:
    """État synthétique d'une nappe à partir de sa chronique piézométrique."""

    code_bss: str
    date_mesure: pd.Timestamp  # date du dernier point (tz-naive, jour)
    niveau_ngf: float  # m NGF
    profondeur_m: float | None  # m sous le sol (positif = sous la surface)
    age_jours: int  # fraîcheur du dernier point vs `now`
    # Position dans la distribution du MOIS courant, sur tout l'historique.
    mois: int
    percentile_saison: int  # 0-100
    mediane_saison_ngf: float
    min_saison_ngf: float
    max_saison_ngf: float
    n_annees_saison: int
    # Tendance récente (variation sur ~30 jours), None si historique court.
    delta_30j_m: float | None
    # Plus-bas absolu de tout l'historique (référence d'étiage sévère).
    plus_bas_date: pd.Timestamp
    plus_bas_ngf: float

    @property
    def classe_saison(self) -> str:
        """`bas` / `normal` / `haut` pour la saison (percentile du mois)."""
        if self.percentile_saison < SEUIL_PERCENTILE_BAS:
            return "bas"
        if self.percentile_saison > SEUIL_PERCENTILE_HAUT:
            return "haut"
        return "normal"


def recuperer_chronique(
    code_bss: str = CODE_BSS_BONNEMAIN,
    timeout: float = 30.0,
    session: requests.Session | None = None,
) -> list[dict] | None:
    """Récupère la chronique brute (liste de mesures) pour un code BSS.

    Renvoie ``None`` en cas d'erreur réseau/HTTP/format (dégradation
    gracieuse). La liste peut être vide si la station n'a aucune mesure.
    """
    sess = session or requests.Session()
    params = {
        "code_bss": code_bss,
        "size": str(_TAILLE_PAGE),
        "sort": "asc",
        "fields": "date_mesure,niveau_nappe_eau,profondeur_nappe",
    }
    try:
        resp = get_avec_retry(sess, CHRONIQUES_URL, params=params, timeout=timeout)
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Hub'Eau piézo : erreur fetch %s (%s)", code_bss, e)
        return None
    if not isinstance(data, dict):
        return None
    return data.get("data") or []


def parser_etat_nappe(
    mesures: list[dict],
    code_bss: str = CODE_BSS_BONNEMAIN,
    now: pd.Timestamp | None = None,
) -> EtatNappe | None:
    """Calcule l'``EtatNappe`` à partir des mesures brutes Hub'Eau.

    ``now`` (UTC ou naïf) sert au calcul d'âge du dernier point ; défaut =
    maintenant. Renvoie ``None`` si aucune mesure exploitable.
    """
    if not mesures:
        return None

    df = pd.DataFrame(mesures)
    if "date_mesure" not in df.columns or "niveau_nappe_eau" not in df.columns:
        return None
    df["date_mesure"] = pd.to_datetime(df["date_mesure"], errors="coerce")
    df["niveau_nappe_eau"] = pd.to_numeric(df["niveau_nappe_eau"], errors="coerce")
    df = df.dropna(subset=["date_mesure", "niveau_nappe_eau"]).sort_values("date_mesure")
    if df.empty:
        return None

    dernier = df.iloc[-1]
    date_mesure = pd.Timestamp(dernier["date_mesure"]).normalize()
    niveau = float(dernier["niveau_nappe_eau"])
    prof = dernier.get("profondeur_nappe")
    profondeur = float(prof) if pd.notna(prof) else None

    now_ts = pd.Timestamp(now).tz_localize(None) if now is not None else pd.Timestamp.now()
    age_jours = int((now_ts.normalize() - date_mesure).days)

    # Distribution saisonnière : tous les points du même mois calendaire.
    mois = int(date_mesure.month)
    meme_mois = df[df["date_mesure"].dt.month == mois]["niveau_nappe_eau"].to_numpy()
    rang = int((meme_mois < niveau).sum())
    percentile = round(100 * rang / len(meme_mois)) if len(meme_mois) else 50
    n_annees = int(df[df["date_mesure"].dt.month == mois]["date_mesure"].dt.year.nunique())

    # Tendance ~30 j : point le plus proche de J-30.
    delta_30j: float | None = None
    cible = date_mesure - pd.Timedelta(days=30)
    avant = df[df["date_mesure"] <= cible]
    if not avant.empty:
        ref = avant.iloc[-1]
        # On exige que le point de référence ne soit pas trop ancien (> 60 j).
        if (date_mesure - pd.Timestamp(ref["date_mesure"]).normalize()).days <= 60:
            delta_30j = round(niveau - float(ref["niveau_nappe_eau"]), 2)

    bas = df.iloc[int(df["niveau_nappe_eau"].to_numpy().argmin())]

    return EtatNappe(
        code_bss=code_bss,
        date_mesure=date_mesure,
        niveau_ngf=round(niveau, 2),
        profondeur_m=round(profondeur, 2) if profondeur is not None else None,
        age_jours=age_jours,
        mois=mois,
        percentile_saison=percentile,
        mediane_saison_ngf=round(float(pd.Series(meme_mois).median()), 2),
        min_saison_ngf=round(float(meme_mois.min()), 2),
        max_saison_ngf=round(float(meme_mois.max()), 2),
        n_annees_saison=n_annees,
        delta_30j_m=delta_30j,
        plus_bas_date=pd.Timestamp(bas["date_mesure"]).normalize(),
        plus_bas_ngf=round(float(bas["niveau_nappe_eau"]), 2),
    )


def etat_nappe(
    code_bss: str = CODE_BSS_BONNEMAIN,
    now: pd.Timestamp | None = None,
    timeout: float = 30.0,
    session: requests.Session | None = None,
) -> EtatNappe | None:
    """Fetch + parse : ``EtatNappe`` pour un code BSS, ``None`` si indispo."""
    mesures = recuperer_chronique(code_bss, timeout=timeout, session=session)
    if mesures is None:
        return None
    return parser_etat_nappe(mesures, code_bss=code_bss, now=now)
