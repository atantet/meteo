"""Source météo : prévision **officielle Météo-France** (roulante, au point).

Cf. **ADR-0014**. Contrairement aux modèles bruts (Single Runs, ``openmeteo_runs``),
cette source renvoie la **prévision grand public de Météo-France** — produit fusionné
et expertisé exposé par le backend de l'appli/site (``webservice.meteofrance.com``).
Elle fournit **au point, en un seul JSON** : pictogramme (orage inclus), proba de
pluie calibrée, T/HR/vent/pluie/nébulosité, en **roulant** (pas de run ; champ
``updated_on``). Utilisée par l'**App 1 (Veille)** ; l'App 2 reste sur Single Runs.

Nature & limites assumées (ADR-0014 D9) :

- **Source d'autorité opaque** : fusion multi-modèles + expertise humaine, **non
  reproductible**, **accès non officiel** (token mobile, hors licence Etalab). On
  l'assume pour le *verdict* (picto/proba), pas pour le calcul scientifique.
- **Pas de rayonnement / ETP** : la Veille n'en calcule pas (l'ETP est l'affaire de
  l'App 2, sur ARPEGE).

Faits vérifiés par sonde (2026-06-06) repris ici :

- ``forecast`` : pas **horaire** jusqu'à ~00:00 **UTC** de J+2, puis 3 h puis 6 h.
- **Vent en m/s** (croisé avec Open-Meteo : ratio ~1, pas ~3,6 → ce n'est pas du
  km/h), T en °C, HR et nébulosité en %, pluie en mm.
- ``probability_forecast`` : proba (%) de pluie par fenêtres 3 h puis 6 h.
- ``weather.desc`` = libellé FR **écrit par Météo-France** (autorité) → on en dérive
  le code OMM 4677 par ``desc_vers_wmo`` (classifieur par mots-clés, sans dépendance
  externe — cf. guide officiel des pictogrammes MF).
"""

from __future__ import annotations

import logging
import os
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import requests

from ._http_retry import get_avec_retry

logger = logging.getLogger(__name__)

# Backend de la prévision officielle MF (appli/site). Token mobile : valeur
# publique par défaut, surchargeable par l'environnement (secrets-agnostique).
WEBSERVICE_URL = "https://webservice.meteofrance.com/forecast"
ENV_TOKEN = "METEOFRANCE_WS_TOKEN"
DEFAULT_TOKEN = "__Wj7dVSTjV9YGu1guveLyDq0g7S7TfTjaHBTPTpO0kj8__"  # noqa: S105


class PrevisionIndisponibleError(RuntimeError):
    """La prévision officielle MF est inexploitable (réseau, payload vide)."""


def _norm(desc: str) -> str:
    """Minuscule sans accents, pour un matching robuste des libellés MF."""
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", desc) if unicodedata.category(c) != "Mn"
    )
    return sans_accents.lower().strip()


def desc_vers_wmo(desc: str) -> int | None:
    """Code OMM 4677 dérivé du libellé ``weather.desc`` de Météo-France.

    Classifieur **par mots-clés** sur le texte autoritaire de MF (aucune table
    tierce). Gère les libellés courts du webservice (« Couvert », « Averses
    faibles », « Orages ») comme les libellés composés du guide officiel des
    pictogrammes MF (« Couvert, Pluies Modérées ou fortes », « Variable, Averses
    de Neige »…). Ne produit que des codes rendus par ``apps.shared.pictograms``
    (icônes yr). Renvoie ``None`` si le libellé est vide ou non reconnu (l'appelant
    log et omet le picto).
    """
    d = _norm(desc)
    if not d:
        return None

    # Orage = verdict prioritaire (MF fait autorité, cf. ADR-0014 D7/D10).
    if "orage" in d:
        return 96 if "grele" in d else 95
    if "grele" in d:  # averses / risque de grêle sans mention d'orage
        return 96

    forte = "fort" in d or "violent" in d
    moderee = "moder" in d
    faible = any(k in d for k in ("faible", "rare", "epars", "quelques"))
    averse = "averse" in d
    neige = "neige" in d or "flocon" in d

    # Pluie et neige mêlées → neige fondue (sleet).
    if neige and "pluie" in d:
        return 67 if forte else 66
    # Neige seule.
    if neige:
        if averse:
            return 86 if forte else 85
        if forte:
            return 75
        if moderee:
            return 73
        return 71
    # Pluie verglaçante / verglas.
    if "verglac" in d or "verglas" in d:
        return 67 if forte else 66
    # Bruine (sauf si qualifiée modérée/forte → traitée comme pluie).
    if "bruine" in d and not (moderee or forte):
        return 51
    # Averses de pluie.
    if averse:
        if forte:
            return 82
        if faible:
            return 80
        return 81
    # Pluie continue.
    if "pluie" in d:
        if forte:
            return 65
        if faible:
            return 61
        return 63  # « Pluie » / « Pluie modérée » → modérée par défaut
    # Brouillard / brume.
    if "brouillard" in d or "brume" in d:
        return 48 if "givrant" in d else 45
    # Nébulosité (du plus couvert au plus clair ; « peu nuageux » avant « nuageux »).
    if "tres nuageux" in d or "couvert" in d:
        return 3
    if "peu nuageux" in d:
        return 1
    if any(k in d for k in ("nuageux", "voile", "eclaircie", "variable")):
        return 2
    if any(k in d for k in ("ensoleille", "soleil", "clair")):
        return 0

    return None


@dataclass
class PrevisionMF:
    """Prévision officielle MF au point + provenance (ADR-0014)."""

    df: pd.DataFrame  # index UTC tz-aware, colonnes socle
    updated_on: pd.Timestamp  # UTC tz-aware : fraîcheur officielle
    position: dict[str, Any]  # name, lat, lon, alti, timezone…


def _serie_proba(prob_entries: list[dict], index: pd.Index) -> pd.Series:
    """Proba de pluie (%) MF diffusée sur la grille horaire ``index``.

    Chaque entrée ``probability_forecast`` porte ``dt`` (début de fenêtre) et
    ``rain`` = {``"3h"``, ``"6h"``} en %. On remplit chaque heure de la fenêtre
    ([dt ; dt+pas[) avec la valeur ; pas = 3 h si la clé 3 h est présente, sinon
    6 h. L'affichage agrège ensuite par ``max`` sur sa période (ADR-0014).
    """
    par_heure: dict[pd.Timestamp, float] = {}
    for e in prob_entries:
        rain = e.get("rain") or {}
        val = rain.get("3h")
        pas = 3
        if val is None:
            val = rain.get("6h")
            pas = 6
        if val is None:
            continue
        debut = pd.Timestamp(e["dt"], unit="s", tz="UTC")
        for k in range(pas):
            par_heure[debut + pd.Timedelta(hours=k)] = float(val)
    if not par_heure:
        return pd.Series(index=index, dtype="float64", name="probabilite_pluie_pct")
    s = pd.Series(par_heure, name="probabilite_pluie_pct").sort_index()
    return s.reindex(index)


@dataclass
class MeteoFranceOfficiel:
    """Client de la prévision officielle MF (App 1 Veille).

    Parameters
    ----------
    session :
        Session HTTP réutilisable (injecter un mock dans les tests).
    timeout :
        Timeout par requête (s).
    token :
        Token webservice MF. Par défaut : env ``METEOFRANCE_WS_TOKEN`` sinon la
        valeur publique connue (secrets-agnostique).
    """

    session: requests.Session = field(default_factory=requests.Session)
    timeout: float = 30.0
    token: str = field(default_factory=lambda: os.environ.get(ENV_TOKEN, DEFAULT_TOKEN))

    def obtenir_prevision(self, latitude: float, longitude: float) -> PrevisionMF:
        """Récupère et parse la prévision officielle MF au point.

        Lève ``PrevisionIndisponibleError`` si le réseau échoue ou si le payload
        n'a pas de bloc ``forecast`` exploitable (la Veille est mono-source MF :
        sans prévision, pas de mail météo).
        """
        params = {
            "lat": f"{latitude}",
            "lon": f"{longitude}",
            "lang": "fr",
            "token": self.token,
        }
        try:
            response = get_avec_retry(
                self.session, WEBSERVICE_URL, params=params, timeout=self.timeout
            )
        except requests.RequestException as e:
            # HTTP (4xx/5xx) ou réseau (ConnectTimeout : webservice MF injoignable
            # par intermittence depuis les runners CI, cf. _http_retry).
            raise PrevisionIndisponibleError(f"Prévision MF inaccessible : {e}") from e
        payload = response.json()
        return self.parser(payload)

    @staticmethod
    def parser(payload: dict) -> PrevisionMF:
        """Parse le JSON webservice MF vers une ``PrevisionMF`` (unités socle).

        Conversions vers le socle : T °C→K ; HR %→fraction ; nébulosité %→fraction ;
        **vent m/s (pas de conversion, vérifié)** ; pluie mm. ``weather_code`` dérivé
        de ``weather.desc`` (``desc_vers_wmo``). La proba (%) est diffusée par
        ``_serie_proba``. ``direction`` négative (vent variable) → NaN.
        """
        forecast = payload.get("forecast") if isinstance(payload, dict) else None
        if not forecast:
            raise PrevisionIndisponibleError("Payload MF sans bloc 'forecast'.")

        lignes: list[dict[str, Any]] = []
        inconnus: set[str] = set()
        for e in forecast:
            desc = (e.get("weather") or {}).get("desc") or ""
            code = desc_vers_wmo(desc)
            if code is None and desc:
                inconnus.add(desc)
            t = e.get("T") or {}
            wind = e.get("wind") or {}
            rain = e.get("rain") or {}
            # Pluie : cumul du pas (1 h en partie horaire ; 3 h/6 h au-delà). La
            # Veille n'exploite que la partie horaire (ADR-0014 D4) → 1 h ici.
            precip = rain.get("1h")
            if precip is None:
                precip = rain.get("3h", rain.get("6h"))
            direction = wind.get("direction")
            t_val = t.get("value")
            hum = e.get("humidity")
            clouds = e.get("clouds")
            lignes.append(
                {
                    "time": pd.Timestamp(e["dt"], unit="s", tz="UTC"),
                    "temperature_2m": (t_val + 273.15) if t_val is not None else None,
                    "humidite_relative": (hum / 100.0) if hum is not None else None,
                    "precipitation": precip,
                    "vitesse_vent_10m": wind.get("speed"),  # m/s (vérifié)
                    "rafales_vent_10m": wind.get("gust"),  # m/s
                    "direction_vent_deg": (
                        direction if (direction is not None and direction >= 0) else None
                    ),
                    "cloud_cover": (clouds / 100.0) if clouds is not None else None,
                    "weather_code": code,
                }
            )
        if inconnus:
            logger.warning("desc MF non reconnus (picto omis) : %s", sorted(inconnus))

        df = pd.DataFrame(lignes).set_index("time").sort_index()
        df["weather_code"] = df["weather_code"].astype("Int64")

        proba = _serie_proba(payload.get("probability_forecast") or [], df.index)
        df["probabilite_pluie_pct"] = proba

        upd = payload.get("updated_on")
        updated_on = pd.Timestamp(upd, unit="s", tz="UTC") if upd else pd.Timestamp.now(tz="UTC")
        position = payload.get("position") or {}
        return PrevisionMF(df=df, updated_on=updated_on, position=position)
