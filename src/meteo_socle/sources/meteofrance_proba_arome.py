"""Proba de pluie PE-AROME (ensemble AROME) **directe** depuis MF, au point.

Remplaçante de la proba calibrée du webservice (bloqué, cf. ADR-0021) pour la
**48 h**. PE-AROME ne sert pas les membres bruts mais des **probabilités déjà
calculées par MF** : famille ``N_PROBA_PRECI{fenetre}_{seuil}`` = P(pluie > seuil mm
sur la fenêtre h). Donc **un champ, pas d'agrégation de membres**. Vérifié au point
le 2026-06-15 : valeur en **% (0-100)**, échéances jusqu'à **+51 h** (couvre la 48 h).

Même WCS Données Publiques (clé DP, joignable CI) et primitives qu'``meteofrance_arome``.
La 48 h utilise la fenêtre **6 h** (grille par tranches de 6 h) ; la semaine pourrait
utiliser la 12 h — mais PE-AROME s'arrête à ~48 h (au-delà = produit stat PE-ARPEGE,
différé, cf. ADR-0021).
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from meteo_socle.sources.meteofrance_arpege import (
    ENV_BASIC,
    ArpegeIndisponibleError,
    _bearer,
    _coverage_run,
    _echeances,
    _valeur_point,
)

logger = logging.getLogger(__name__)

WCS_BASE = "https://public-api.meteofrance.fr/public/pearome/1.0/wcs/MF-NWP-HIGHRES-PEAROME-0025-FRANCE-WCS"
_MAX_WORKERS = 6
#: Seuils (mm) disponibles par fenêtre dans `N_PROBA_PRECI{fenetre}_{seuil}` (cf.
#: GetCapabilities PE-AROME) — garde-fou pour ne pas demander un coverage inexistant.
SEUILS_DISPO: dict[int, tuple[int, ...]] = {
    1: (1, 5, 10, 20, 40),
    3: (1, 5, 10, 20, 40, 80),
    6: (1, 5, 10, 20, 40, 60, 100),
    12: (5, 10, 20, 40, 60, 100, 150),
    24: (5, 10, 20, 50, 80, 120, 200),
}


class ProbaAromeIndisponibleError(RuntimeError):
    """PE-AROME inaccessible (le champ proba ne peut pas être construit)."""


def _coverage_prefixe(fenetre_h: int, seuil_mm: int) -> str:
    return f"N_PROBA_PRECI{fenetre_h:02d}_{seuil_mm}__GROUND_OR_WATER_SURFACE"


class MeteoFranceProbaArome:
    """Proba pluie PE-AROME (P > seuil/fenêtre), au point, en % — pour la 48 h."""

    def __init__(self, basic: str | None = None, session: requests.Session | None = None) -> None:
        self.basic = basic or os.environ.get(ENV_BASIC, "")
        self.session = session or requests.Session()

    def obtenir_proba(
        self,
        run_utc: pd.Timestamp,
        latitude: float,
        longitude: float,
        horizon_jours: int = 2,
        fenetre_h: int = 6,
        seuil_mm: int = 1,
    ) -> pd.Series:
        """Série proba pluie (%) P(> ``seuil_mm`` mm / ``fenetre_h`` h), indexée UTC.

        ``fenetre_h``/``seuil_mm`` doivent figurer dans ``SEUILS_DISPO``. La série porte
        le nom ``probabilite_pluie_pct`` (convention App 1) ; valeurs déjà en % (0-100,
        pas de conversion). Lève ``ProbaAromeIndisponibleError`` si auth/WCS KO.
        """
        if seuil_mm not in SEUILS_DISPO.get(fenetre_h, ()):
            raise ValueError(f"Seuil {seuil_mm} mm indisponible pour la fenêtre {fenetre_h} h.")
        if not self.basic:
            raise ProbaAromeIndisponibleError(f"Identifiant {ENV_BASIC} absent.")
        run_utc = run_utc.tz_convert("UTC") if run_utc.tzinfo else run_utc.tz_localize("UTC")
        prefixe = _coverage_prefixe(fenetre_h, seuil_mm)
        try:
            token = _bearer(self.session, self.basic)
            echeances = [
                t
                for t in _echeances(
                    self.session, token, run_utc, wcs_base=WCS_BASE, coverage_prefixe=prefixe
                )
                if t <= run_utc + pd.Timedelta(days=horizon_jours)
            ]
        except (ArpegeIndisponibleError, requests.RequestException) as e:
            raise ProbaAromeIndisponibleError(f"Échéances PE-AROME indisponibles : {e}") from e
        if not echeances:
            raise ProbaAromeIndisponibleError("Aucune échéance PE-AROME.")
        run_str = _coverage_run(run_utc)
        cid = f"{prefixe}___{run_str}"

        def _run(t: pd.Timestamp) -> tuple[pd.Timestamp, float]:
            try:
                val = _valeur_point(
                    self.session, token, cid, t, latitude, longitude, None, wcs_base=WCS_BASE
                )
                return t, val
            except ArpegeIndisponibleError as e:
                logger.warning("Proba PE-AROME : %s", e)
                return t, float("nan")

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            paires = list(pool.map(_run, echeances))
        serie = pd.Series({t: v for t, v in paires}, name="probabilite_pluie_pct").sort_index()
        serie.index.name = "time"
        return serie
