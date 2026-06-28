"""Indice UV journalier PHEALTH depuis DPPaquetENVIRONNEMENT (portail-api MF, clé DP).

Modèle PHEALTH, grille France EURW1S40 (0,025°, ~2,7 km). Retourne ``uvi`` (indice UV
réel, max journalier) pour J0 et J1 en une seule requête GRIB2.

Conventions GRIB2 (vérifiées 2026-06-28) :
  - ``stepRange=0-24``  → max UV du **jour du run** (J0) ;
  - ``stepRange=24-48`` → max UV du **lendemain** (J1).
La ``valid_time`` GRIB2 est la **fin** de la fenêtre d'accumulation (J0+1 jour,
J1+1 jour) — ne pas confondre avec le jour prévu.

Auth : même OAuth Basic DP que AROME/ARPEGE (``METEOFRANCE_DP_BASIC``).
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from meteo_socle.sources.meteofrance_arpege import ENV_BASIC, _bearer

logger = logging.getLogger(__name__)

PHEALTH_URL = (
    "https://public-api.meteofrance.fr/previnum/DPPaquetENVIRONNEMENT/v1"
    "/models/PHEALTH/grids/EURW1S40/packages/UVQ/productPHEALTH"
)
_PHEALTH_TIME = "001H051H"

# Échelle OMS/WHO : (seuil entier inclusif, libellé, couleur hex).
_NIVEAUX_OMS: tuple[tuple[int, str, str], ...] = (
    (2, "Faible", "#57A032"),
    (5, "Modéré", "#D4B800"),
    (7, "Élevé", "#E65B00"),
    (10, "Très élevé", "#CC0000"),
    (99, "Extrême", "#6B49C8"),
)


def libelle_uv_oms(uvi: float) -> tuple[str, str]:
    """Retourne (libellé, couleur_hex) OMS pour un indice UV."""
    uvi_int = round(uvi)
    for seuil, label, couleur in _NIVEAUX_OMS:
        if uvi_int <= seuil:
            return label, couleur
    return "Extrême", "#6B49C8"


class PheaithIndisponibleError(RuntimeError):
    """Auth ou endpoint PHEALTH inaccessible (UV omis, non bloquant)."""


@dataclass
class UVJournalier:
    """UV max journalier (indice réel) pour J0 (jour du run) et J1 (lendemain)."""

    uvi_j0: float
    uvi_j1: float
    run_utc: pd.Timestamp


def _cache_path(run_utc: pd.Timestamp, cache_dir: str | Path) -> Path:
    return Path(cache_dir) / f"phealth_{run_utc.strftime('%Y%m%dT%HZ')}.grib2"


def _extraire_uv(grib_path: Path, latitude: float, longitude: float) -> tuple[float, float]:
    """Extrait (uvi_j0, uvi_j1) au point le plus proche depuis le GRIB2 PHEALTH."""
    try:
        import cfgrib
    except ImportError as exc:
        raise PheaithIndisponibleError("cfgrib requis pour lire PHEALTH") from exc
    try:
        ds_list = cfgrib.open_datasets(str(grib_path))
    except Exception as exc:
        raise PheaithIndisponibleError(f"Lecture GRIB2 PHEALTH échouée : {exc}") from exc
    if not ds_list or "uvi" not in ds_list[0]:
        raise PheaithIndisponibleError("Champ uvi absent du GRIB2 PHEALTH.")
    ds = ds_list[0]
    lat_idx = int(np.abs(ds.latitude.values - latitude).argmin())
    lon_idx = int(np.abs(ds.longitude.values - longitude).argmin())
    uvi_vals = ds["uvi"].values[:, lat_idx, lon_idx]  # shape (2,) : J0, J1
    uvi_j0 = float(uvi_vals[0]) if len(uvi_vals) > 0 else float("nan")
    uvi_j1 = float(uvi_vals[1]) if len(uvi_vals) > 1 else float("nan")
    return uvi_j0, uvi_j1


def obtenir_uv(
    run_utc: pd.Timestamp,
    latitude: float,
    longitude: float,
    basic: str | None = None,
    session: requests.Session | None = None,
    cache_dir: str | Path | None = None,
) -> UVJournalier:
    """Télécharge (ou charge depuis cache) le GRIB2 PHEALTH et extrait uvi J0/J1 au point.

    Lève ``PheaithIndisponibleError`` ou ``requests.RequestException`` en cas d'échec —
    les deux sont attrapés par l'appelant comme erreur non bloquante.
    """
    session = session or requests.Session()
    _basic = basic or os.environ.get(ENV_BASIC, "")
    if not _basic:
        raise PheaithIndisponibleError(f"Identifiant {ENV_BASIC} absent.")

    if cache_dir:
        cp = _cache_path(run_utc, cache_dir)
        if cp.exists():
            logger.debug("PHEALTH cache hit : %s", cp)
            j0, j1 = _extraire_uv(cp, latitude, longitude)
            return UVJournalier(uvi_j0=j0, uvi_j1=j1, run_utc=run_utc)

    params = {
        "referencetime": run_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time": _PHEALTH_TIME,
        "format": "grib2",
    }
    try:
        token = _bearer(session, _basic)
        resp = session.get(
            PHEALTH_URL,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise PheaithIndisponibleError(
            f"Fetch PHEALTH échoué ({run_utc:%Y-%m-%dT%HZ}) : {exc}"
        ) from exc

    if cache_dir:
        cp = _cache_path(run_utc, cache_dir)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_bytes(resp.content)
        j0, j1 = _extraire_uv(cp, latitude, longitude)
    else:
        with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = Path(tmp.name)
        try:
            j0, j1 = _extraire_uv(tmp_path, latitude, longitude)
        finally:
            tmp_path.unlink(missing_ok=True)

    return UVJournalier(uvi_j0=j0, uvi_j1=j1, run_utc=run_utc)
