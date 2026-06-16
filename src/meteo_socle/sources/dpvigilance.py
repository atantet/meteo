"""Vigilance Météo-France via **DPVigilance** (`portail-api`, clé DP) — au département.

Remplace ``meteofrance_vigilance`` (endpoint webservice ``currentphenomenons``), qui
est sur le **backend bloqué depuis les runners** ET trop grossier (un niveau courant,
pas de découpage temporel). DPVigilance (``public-api.meteofrance.fr``, OAuth clé DP,
**joignable depuis CI**) sert le bulletin « carte » : **périodes J/J+1** avec, par
département et par phénomène, des **tranches horodatées** ``timelaps_items``
(``begin_time``/``end_time`` ISO **UTC**, ``color_id`` 1-4).

C'est ce qui permet, côté App 1 (ADR-0021), de **brancher le picto orage sur la
Vigilance** (doctrine « une seule méthode / phénomène ») avec compatibilité
matin/après-midi : on intersecte les tranches « orages » du dept avec les fenêtres
picto. La couleur jaune (2) **est** horodatée (vérifié 2026-06-15).

Structure JSON (vérifiée au point) :
``product.periods[].timelaps.domain_ids[].phenomenon_items[].timelaps_items[]``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import pandas as pd
import requests

from meteo_socle.sources.meteofrance_arpege import ENV_BASIC, _bearer

logger = logging.getLogger(__name__)

DPVIGILANCE_URL = "https://public-api.meteofrance.fr/public/DPVigilance/v1/cartevigilance/encours"
ORAGES_ID = 3

# Codes officiels MF des phénomènes Vigilance.
PHENOMENES_NOMS: dict[int, str] = {
    1: "Vent violent",
    2: "Pluie-inondation",
    3: "Orages",
    4: "Crues",
    5: "Neige-verglas",
    6: "Canicule",
    7: "Grand froid",
    8: "Avalanches",
    9: "Vagues-submersion",
}
# Phénomènes pertinents pour Pleine-Fougères (35) maraîchage + blé (cf. doctrine
# « une seule méthode par phénomène »). Crues/avalanches/vagues sans objet ici.
PHENOMENES_PERTINENTS: tuple[int, ...] = (1, 2, 3, 5, 6, 7)
# Couleurs Vigilance MF (1=vert .. 4=rouge).
NIVEAU_NOMS: dict[int, str] = {1: "Vert", 2: "Jaune", 3: "Orange", 4: "Rouge"}


class VigilanceDPIndisponibleError(RuntimeError):
    """DPVigilance inaccessible (auth/réseau) ou payload inexploitable."""


@dataclass
class TrancheVigilance:
    """Fenêtre horodatée (UTC) à un niveau de vigilance donné, pour un phénomène."""

    debut: pd.Timestamp
    fin: pd.Timestamp
    niveau: int  # 1 (vert) .. 4 (rouge)


@dataclass
class VigilancePhenomeneDP:
    """Vigilance d'un phénomène au département : niveau max + tranches horodatées.

    ``niveau`` est un alias de ``niveau_max`` (compatibilité avec le rendu mail, qui
    lit ``phenomene.niveau``).
    """

    code: int
    nom: str
    niveau_max: int
    tranches: list[TrancheVigilance] = field(default_factory=list)

    @property
    def niveau(self) -> int:
        return self.niveau_max


@dataclass
class VigilanceDepartementDP:
    """Vigilance DPVigilance d'un département (phénomènes pertinents), J + J+1.

    Expose la même surface que ``VigilanceDepartement`` (webservice) pour rester
    **drop-in** côté rendu mail : ``departement``, ``update_time``, ``fin_validite``,
    ``niveau_max_global`` (propriété), ``phenomenes[].niveau``/``.nom``.
    """

    departement: str
    phenomenes: list[VigilancePhenomeneDP]
    update_time: pd.Timestamp | None = None  # émission (meta)
    fin_validite: pd.Timestamp | None = None  # fin de validité (J+1)

    def phenomene(self, code: int) -> VigilancePhenomeneDP | None:
        return next((p for p in self.phenomenes if p.code == code), None)

    def niveau(self, code: int) -> int:
        ph = self.phenomene(code)
        return ph.niveau_max if ph else 1

    def tranches_orages(self, niveau_min: int = 2) -> list[TrancheVigilance]:
        """Tranches orages ≥ ``niveau_min`` (défaut jaune), pour l'overlay picto."""
        ph = self.phenomene(ORAGES_ID)
        if ph is None:
            return []
        return [t for t in ph.tranches if t.niveau >= niveau_min]

    @property
    def niveau_max_global(self) -> int:
        return max((p.niveau_max for p in self.phenomenes), default=1)


def _ts(valeur: object) -> pd.Timestamp | None:
    """ISO 8601 (``...Z``) → Timestamp UTC ; None si vide/illisible."""
    if not valeur:
        return None
    try:
        return pd.Timestamp(str(valeur)).tz_convert("UTC")
    except (ValueError, TypeError):
        return None


def parser_vigilance_dp(data: dict, departement: str) -> VigilanceDepartementDP:
    """Parse le JSON DPVigilance « carte » → vigilance du ``departement``.

    Accumule, par phénomène pertinent, les ``timelaps_items`` de toutes les périodes
    (J, J+1) ; le niveau max vient du pire ``color_id`` rencontré. Les phénomènes
    absents → niveau 1 (vert), sans tranche.
    """
    product = data.get("product") or {}
    periods = product.get("periods") or []
    if not periods:
        raise VigilanceDPIndisponibleError("Payload DPVigilance sans périodes.")
    meta = data.get("meta") or {}
    update_time = _ts(
        meta.get("update_time") or meta.get("produced_on") or product.get("update_time")
    )
    if update_time is None:  # fallback : début de validité (≈ émission du cycle).
        debuts = [_ts(p.get("begin_validity_time")) for p in periods]
        update_time = min((t for t in debuts if t is not None), default=None)
    fins = [_ts(p.get("end_validity_time")) for p in periods]
    fin_validite = max((t for t in fins if t is not None), default=None)
    tranches: dict[int, list[TrancheVigilance]] = {pid: [] for pid in PHENOMENES_PERTINENTS}
    for per in periods:
        domains = (per.get("timelaps") or {}).get("domain_ids") or []
        dom = next((d for d in domains if str(d.get("domain_id")) == str(departement)), None)
        if dom is None:
            continue
        for item in dom.get("phenomenon_items") or []:
            pid = int(item.get("phenomenon_id", 0))
            if pid not in tranches:
                continue
            for tl in item.get("timelaps_items") or []:
                debut, fin = _ts(tl.get("begin_time")), _ts(tl.get("end_time"))
                niveau = int(tl.get("color_id", 1))
                if debut is not None and fin is not None:
                    tranches[pid].append(TrancheVigilance(debut, fin, niveau))
    phenomenes = [
        VigilancePhenomeneDP(
            code=pid,
            nom=PHENOMENES_NOMS[pid],
            niveau_max=max((t.niveau for t in tr), default=1),
            tranches=sorted(tr, key=lambda t: t.debut),
        )
        for pid, tr in tranches.items()
    ]
    return VigilanceDepartementDP(
        departement=str(departement),
        phenomenes=phenomenes,
        update_time=update_time,
        fin_validite=fin_validite,
    )


def recuperer_vigilance_dp(
    departement: str,
    basic: str | None = None,
    session: requests.Session | None = None,
) -> VigilanceDepartementDP:
    """Récupère et parse la Vigilance DP du département (clé DP, joignable CI)."""
    basic = basic or os.environ.get(ENV_BASIC, "")
    if not basic:
        raise VigilanceDPIndisponibleError(f"Identifiant {ENV_BASIC} absent.")
    session = session or requests.Session()
    try:
        token = _bearer(session, basic)
        resp = session.get(
            DPVIGILANCE_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=(10.0, 40.0),
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise VigilanceDPIndisponibleError(f"DPVigilance inaccessible : {e}") from e
    return parser_vigilance_dp(data, departement)
