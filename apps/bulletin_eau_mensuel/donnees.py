"""Collecte et structuration des données du bulletin eau mensuel.

Assemble les trois piliers (nappe, restrictions, pluie) en un
``BulletinEau``. Chaque pilier est **optionnel** : si une source échoue,
son champ vaut ``None`` et le bloc correspondant est omis du mail
(dégradation gracieuse).

Le calcul de l'écart de pluie à la normale est une fonction pure et
testable (``calcul_anomalie_pluie``), sans accès réseau.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from meteo_socle.sources.era5_cds import Era5Cds
from meteo_socle.sources.hubeau_piezo import EtatNappe, etat_nappe
from meteo_socle.sources.vigieau import RestrictionsEau, recuperer_restrictions

logger = logging.getLogger(__name__)

# Bornes de classification de l'écart de pluie (%) à la normale.
SEUIL_ECART_DEFICIT = -15
SEUIL_ECART_EXCEDENT = 15


@dataclass(frozen=True)
class AnomaliePluie:
    """Écart du cumul de pluie récent à la normale (réanalyse)."""

    debut: pd.Timestamp
    fin: pd.Timestamp
    fenetre_jours: int
    cumul_mm: float
    normale_mm: float
    ref_debut_annee: int
    ref_fin_annee: int

    @property
    def ecart_mm(self) -> float:
        return round(self.cumul_mm - self.normale_mm, 1)

    @property
    def ecart_pct(self) -> int:
        if self.normale_mm == 0:
            return 0
        return round(100 * (self.cumul_mm - self.normale_mm) / self.normale_mm)

    @property
    def classe(self) -> str:
        """`déficitaire` / `normale` / `excédentaire`."""
        if self.ecart_pct < SEUIL_ECART_DEFICIT:
            return "déficitaire"
        if self.ecart_pct > SEUIL_ECART_EXCEDENT:
            return "excédentaire"
        return "normale"


@dataclass(frozen=True)
class BulletinEau:
    """Données assemblées du bulletin (piliers optionnels)."""

    genere_le: pd.Timestamp
    commune_insee: str
    nom_station_nappe: str
    nappe: EtatNappe | None
    restrictions: RestrictionsEau | None
    pluie: AnomaliePluie | None


def calcul_anomalie_pluie(
    obs: pd.Series,
    ref: pd.Series,
    fin: pd.Timestamp,
    fenetre_jours: int = 90,
    couverture_min: float = 0.8,
) -> AnomaliePluie | None:
    """Écart du cumul observé sur ``fenetre_jours`` à la normale de réf.

    Parameters
    ----------
    obs :
        Série quotidienne de pluie (mm) observée récente, index date.
    ref :
        Série quotidienne de pluie (mm) sur la période de référence
        (p. ex. 1991-2020), index date.
    fin :
        Dernier jour de la fenêtre récente (inclus).
    fenetre_jours :
        Largeur de la fenêtre glissante (défaut 90 = ~3 mois).
    couverture_min :
        Fraction minimale de jours présents pour qu'une année de référence
        compte dans la normale (filtre les années incomplètes).

    Returns
    -------
    AnomaliePluie | None
        ``None`` si la fenêtre récente est vide ou si aucune année de
        référence n'a une couverture suffisante.
    """
    if obs.empty or ref.empty:
        return None
    fin = pd.Timestamp(fin).normalize()
    debut = fin - pd.Timedelta(days=fenetre_jours - 1)
    obs_win = obs[(obs.index >= debut) & (obs.index <= fin)]
    if obs_win.empty:
        return None
    cumul = float(obs_win.sum())

    seuil_jours = couverture_min * fenetre_jours
    sommes: list[float] = []
    annees_utiles: list[int] = []
    for an in sorted({int(a) for a in ref.index.year}):
        try:
            f = pd.Timestamp(year=an, month=fin.month, day=fin.day)
        except ValueError:
            # 29 février sans correspondance cette année-là.
            continue
        d = f - pd.Timedelta(days=fenetre_jours - 1)
        fen = ref[(ref.index >= d) & (ref.index <= f)]
        if len(fen) >= seuil_jours:
            sommes.append(float(fen.sum()))
            annees_utiles.append(an)
    if not sommes:
        return None

    normale = sum(sommes) / len(sommes)
    return AnomaliePluie(
        debut=debut,
        fin=fin,
        fenetre_jours=fenetre_jours,
        cumul_mm=round(cumul, 1),
        normale_mm=round(normale, 1),
        ref_debut_annee=min(annees_utiles),
        ref_fin_annee=max(annees_utiles),
    )


def _collecter_pluie(
    config: dict[str, Any],
    now_utc: pd.Timestamp,
    archive: Era5Cds | None = None,
) -> AnomaliePluie | None:
    """Récupère obs récente + normale de réf et calcule l'écart (ERA5 CDS)."""
    site = config["site"]
    pcfg = config.get("pluie", {})
    fenetre = int(pcfg.get("fenetre_jours", 90))
    an0 = int(pcfg.get("reference_debut_annee", 1991))
    an1 = int(pcfg.get("reference_fin_annee", 2020))
    arch = archive or Era5Cds()

    # Dernier jour complet = hier (la réanalyse a quelques jours de latence,
    # mais on borne à hier et on laisse la couverture réelle décider).
    fin = pd.Timestamp(now_utc).tz_localize(None).normalize() - pd.Timedelta(days=1)
    debut = fin - pd.Timedelta(days=fenetre + 5)
    try:
        obs = arch.obtenir_precip_quotidien(
            site["latitude"],
            site["longitude"],
            debut.strftime("%Y-%m-%d"),
            fin.strftime("%Y-%m-%d"),
        )
        ref = arch.obtenir_precip_quotidien(
            site["latitude"],
            site["longitude"],
            f"{an0}-01-01",
            f"{an1}-12-31",
        )
    except Exception as e:  # noqa: BLE001 — dégradation gracieuse
        logger.warning("Bulletin eau : pluie indisponible (%s)", e)
        return None
    if obs.empty:
        return None
    fin_reelle = pd.Timestamp(obs.index.max()).normalize()
    return calcul_anomalie_pluie(obs, ref, fin_reelle, fenetre_jours=fenetre)


def collecter_bulletin(
    config: dict[str, Any],
    now_utc: pd.Timestamp | None = None,
    archive: Era5Cds | None = None,
) -> BulletinEau:
    """Assemble le ``BulletinEau`` via les trois sources (live).

    Chaque pilier dégrade gracieusement en ``None`` si sa source échoue.
    """
    now = now_utc if now_utc is not None else pd.Timestamp.now(tz="UTC")
    site = config["site"]
    ncfg = config.get("nappe", {})
    rcfg = config.get("restrictions", {})

    nappe = etat_nappe(code_bss=ncfg.get("code_bss"), now=now)
    restrictions = recuperer_restrictions(
        commune_insee=str(site["commune_insee"]),
        profil=rcfg.get("profil", "exploitation"),
    )
    pluie = _collecter_pluie(config, now, archive)

    return BulletinEau(
        genere_le=pd.Timestamp(now),
        commune_insee=str(site["commune_insee"]),
        nom_station_nappe=ncfg.get("nom_station", ""),
        nappe=nappe,
        restrictions=restrictions,
        pluie=pluie,
    )
