"""AROME France HD 0,01° **direct** depuis Météo-France Données Publiques (WCS), au point.

Source de la **prévision 48 h** d'App 1 (Veille), en remplacement du webservice MF
bloqué depuis les runners GitHub (cf. ADR-0021). AROME passe par le **même WCS
Données Publiques** qu'ARPEGE (`public-api.meteofrance.fr`, clé DP `METEOFRANCE_DP_BASIC`),
**joignable depuis CI**. AROME HD 0,01° (~1,5 km), horaire, échéances jusqu'à ~48 h.

Réutilise les primitives WCS d'``meteofrance_arpege`` (OAuth, limiteur/min,
``_echeances``/``_valeur_point`` paramétrés par ``wcs_base``) ; seules changent la
**collection** et le **mapping variable → coverage**. Ce mapping ajoute les champs
**picto** absents d'ARPEGE-en-prod : type de précip (phase), visibilité (brouillard),
couches nuageuses, neige — tous diagnostiqués par MF (cf. moteur ``temps_sensible``).

Unités vérifiées au point le 2026-06-15 (smoke ``diag_arome_getcoverage``) :
T en **K**, HR en **%** (→ fraction), vent/rafales en **m/s**, **nébulosité en %**
(→ fraction, ÷100, comme ARPEGE — corrigé 2026-06-20), pluie/neige en **mm**, visibilité en **m**,
``PRECIPITATION_TYPE_60_MIN`` = **code GRIB 4.201** (0 = pas de précip), rayonnement
en J/m² accumulés → J/m²/h. Sortie en **unités socle**, mêmes conventions que
``MeteoFranceArpege`` → branchable sans changer le pipeline.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from meteo_socle.sources.meteofrance_arpege import (
    ENV_BASIC,
    ArpegeIndisponibleError,
    _bearer,
    _convertir,
    _coverage_run,
    _echeances,
    _reechantillonner_horaire,
    _suffixe_accum,
    _valeur_point,
    vent_vitesse_direction,
)

logger = logging.getLogger(__name__)

WCS_BASE = (
    "https://public-api.meteofrance.fr/public/arome/1.0/wcs/MF-NWP-HIGHRES-AROME-001-FRANCE-WCS"
)
_MAX_WORKERS = 6


class AromeIndisponibleError(RuntimeError):
    """Auth ou WCS AROME inaccessible (le run ne peut pas être construit)."""


# ---------------------------------------------------------------------------
# Mapping variable socle → coverage AROME (+ niveau, conversion).
# « pct_frac » = % (0-100) → fraction 0-1 (HR, nébulosité). Le WCS AROME sert la
# nébulosité en % comme ARPEGE (même coverage TOTAL_CLOUD_COVER) — l'hypothèse
# « déjà en fraction » était fausse (héritée d'une source antérieure), elle gonflait
# d'un facteur 100 le moteur picto (35 % → « couvert ») [vérifié log PICTO-DIAG 2026-06-20].
# « code » = code GRIB tel quel (type de précip). « m » = mètres (visibilité).
# ---------------------------------------------------------------------------
#: Variables instantanées : (préfixe coverage, hauteur ou None, conversion → socle).
_VARS_INSTANT: dict[str, tuple[str, int | None, str]] = {
    "temperature_2m": ("TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 2, "K"),
    "humidite_relative": ("RELATIVE_HUMIDITY__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 2, "pct_frac"),
    "rafales_vent_10m": ("WIND_SPEED_GUST__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 10, "ms"),
    "cloud_cover": ("TOTAL_CLOUD_COVER__GROUND_OR_WATER_SURFACE", None, "pct_frac"),
    # Couches basse/moyenne : réduction « cirrus » du moteur picto (le couvert sans
    # pluie mais low+mid dégagés → partiel). La couche HAUTE n'est PAS consommée → non
    # fetchée (allègement : un fetch 48 h = ~1 requête WCS par variable × échéance).
    "cloud_cover_low": ("LOW_CLOUD_COVER__GROUND_OR_WATER_SURFACE", None, "pct_frac"),
    "cloud_cover_mid": ("MEDIUM_CLOUD_COVER__GROUND_OR_WATER_SURFACE", None, "pct_frac"),
    # Champs picto diagnostiqués par MF (cf. ADR-0021 / temps_sensible).
    "type_precip": ("PRECIPITATION_TYPE_60_MIN__GROUND_OR_WATER_SURFACE", None, "code"),
    "visibilite_m": ("VISIBILITY_MINI_60MIN__GROUND_OR_WATER_SURFACE", None, "m"),
    # U/V à 10 m → vitesse + direction.
    "_u10": ("U_COMPONENT_OF_WIND__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 10, "ms"),
    "_v10": ("V_COMPONENT_OF_WIND__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 10, "ms"),
}
#: Variables accumulées (suffixe _PT{n}H selon le pas) : (préfixe, conversion).
#: Set minimal pour la 48 h : neige (phase via ``type_precip``, montant non affiché)
#: et rayonnement (pas d'ETP en 48 h) sont **exclus** — non consommés, donc non fetchés.
_VARS_ACCUM: dict[str, tuple[str, str]] = {
    "precipitation": ("TOTAL_PRECIPITATION__GROUND_OR_WATER_SURFACE", "mm"),
}

#: Colonnes accumulées (réparties sur leur fenêtre lors du rééchantillonnage).
_COLS_ACCUM = ("precipitation",)
#: Champs « instantanés » sans valeur à l'analyse (+0 h) — sautés (NaN).
_SANS_ANALYSE = ("rafales_vent_10m", "type_precip", "visibilite_m")


class MeteoFranceArome:
    """Source AROME HD directe MF (WCS Données Publiques), au point, en unités socle."""

    def __init__(self, basic: str | None = None, session: requests.Session | None = None) -> None:
        self.basic = basic or os.environ.get(ENV_BASIC, "")
        self.session = session or requests.Session()

    def obtenir_run(
        self,
        run_utc: pd.Timestamp,
        latitude: float,
        longitude: float,
        horizon_jours: int = 2,
        cache_dir: str | Path | None = None,
    ) -> pd.DataFrame:
        """Série horaire au point pour le run AROME, jusqu'à ``horizon_jours`` (≤ ~2 j).

        DataFrame indexé UTC, colonnes socle + champs picto (``type_precip`` code GRIB,
        ``visibilite_m``, ``cloud_cover_{low,mid,high}``). Accumulées calées sur la
        fenêtre entre échéances ; la 1ʳᵉ (+0 h) → 0. Direction du vent dérivée d'U/V.
        ``cache_dir`` : cache parquet par run+point (réutilisé entre les deux envois).
        """
        if not self.basic:
            raise AromeIndisponibleError(f"Identifiant {ENV_BASIC} absent.")
        run_utc = run_utc.tz_convert("UTC") if run_utc.tzinfo else run_utc.tz_localize("UTC")
        chemin_cache: Path | None = None
        if cache_dir is not None:
            chemin_cache = Path(cache_dir) / (
                f"arome_{run_utc:%Y%m%dT%HZ}_{latitude:.3f}_{longitude:.3f}_h{horizon_jours}.parquet"
            )
            if chemin_cache.exists():
                logger.info("AROME direct : run servi depuis le cache (%s).", chemin_cache.name)
                return pd.read_parquet(chemin_cache)
        try:
            token = _bearer(self.session, self.basic)
            echeances = [
                t
                for t in _echeances(self.session, token, run_utc, wcs_base=WCS_BASE)
                if t <= run_utc + pd.Timedelta(days=horizon_jours)
            ]
        except (ArpegeIndisponibleError, requests.RequestException) as e:
            raise AromeIndisponibleError(f"Échéances AROME indisponibles : {e}") from e
        if not echeances:
            raise AromeIndisponibleError("Aucune échéance AROME.")
        run_str = _coverage_run(run_utc)

        # Fenêtre d'accumulation par échéance = écart avec l'échéance précédente.
        fenetres = {echeances[0]: 0.0}
        for prev, cur in zip(echeances, echeances[1:], strict=False):
            fenetres[cur] = (cur - prev).total_seconds()

        taches: list[tuple[str, pd.Timestamp, str, int | None, str, float]] = []
        for col, (prefixe, hauteur, conv) in _VARS_INSTANT.items():
            for t in echeances:
                if col in _SANS_ANALYSE and t == echeances[0]:
                    continue  # pas de valeur à l'analyse → 404 attendu, on saute.
                taches.append((col, t, f"{prefixe}___{run_str}", hauteur, conv, 3600.0))
        for col, (prefixe, conv) in _VARS_ACCUM.items():
            for t in echeances:
                fen = fenetres[t]
                if fen <= 0:  # +0 h : pas d'accumulation
                    continue
                cid = f"{prefixe}___{run_str}{_suffixe_accum(fen)}"
                taches.append((col, t, cid, None, conv, fen))

        def _run(tache):
            col, t, cid, hauteur, conv, fen = tache
            try:
                brut = _valeur_point(
                    self.session, token, cid, t, latitude, longitude, hauteur, wcs_base=WCS_BASE
                )
                return col, t, _convertir(brut, conv, fen)
            except ArpegeIndisponibleError as e:
                logger.warning("AROME direct : %s", e)
                return col, t, np.nan

        cols = list(_VARS_INSTANT) + list(_VARS_ACCUM)
        df = pd.DataFrame(index=pd.DatetimeIndex(echeances, name="time"), columns=cols, dtype=float)
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            for col, t, val in pool.map(_run, taches):
                df.at[t, col] = val

        for col in _VARS_ACCUM:
            df.loc[echeances[0], col] = 0.0
        df = _reechantillonner_horaire(df, run_utc)  # AROME est horaire → no-op
        df["vitesse_vent_10m"], df["direction_vent_deg"] = vent_vitesse_direction(
            df["_u10"], df["_v10"]
        )
        df = df.drop(columns=["_u10", "_v10"])
        if chemin_cache is not None:
            chemin_cache.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(chemin_cache)
            logger.info("AROME direct : run mis en cache (%s).", chemin_cache.name)
        return df
