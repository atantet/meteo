"""Client Vigilance Météo-France — via le **webservice** (prévi roulante).

Récupère le niveau de Vigilance officiel par département pour les 9 phénomènes
(vent violent, pluie-inondation, orages, crues, neige-verglas, canicule, grand
froid, avalanches, vagues-submersion).

**Source unifiée (ADR-0014)** : la Vigilance vient désormais du **même backend**
que la prévision officielle (``webservice.meteofrance.com``), et non plus de
l'API DPVigilance du portail (OAuth + ``METEOFRANCE_DP_BASIC``). C'est **la même
Vigilance officielle d'État** (celle de l'appli/site MF), servie par le canal de
la prévi roulante → un seul backend, un seul token (public, partagé avec
``meteofrance_officiel``).

Endpoint :
- ``GET /v3/warning/currentphenomenons?domain=<dept>&depth=0`` — niveaux courants
  par phénomène pour le département. Couvre la **période de validité courante**
  (~24 h, ``end_validity_time``), pas un découpage J/J+1.

Le format parsé reste plat : niveau (1-4) par phénomène pertinent + horodatages
(émission ``update_time`` et fin de validité), pour le rendu HTML.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import pandas as pd
import requests

from ._http_retry import get_avec_retry
from .meteofrance_officiel import DEFAULT_TOKEN, ENV_TOKEN

logger = logging.getLogger(__name__)

# Webservice MF (même backend que la prévi officielle, ADR-0014).
WARNING_URL = "https://webservice.meteofrance.com/v3/warning/currentphenomenons"

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

# Phénomènes pertinents pour Pleine-Fougères (35) maraîchage + blé. Crues
# exclues (hors zone Couesnon inondable), avalanches et vagues-submersion sans
# objet sur plateau. Cf. mémoire "une-seule-methode-par-phenomene".
PHENOMENES_PERTINENTS: tuple[int, ...] = (1, 2, 3, 5, 6, 7)

# Couleurs Vigilance MF (1=vert .. 4=rouge).
NIVEAU_NOMS: dict[int, str] = {
    1: "Vert",
    2: "Jaune",
    3: "Orange",
    4: "Rouge",
}

DEPARTEMENT_DEFAUT = "35"


@dataclass
class VigilancePhenomene:
    """Niveau de Vigilance courant pour un phénomène (1=vert .. 4=rouge)."""

    code: int  # 1..9
    nom: str  # libellé court FR
    niveau: int  # 1..4


@dataclass
class VigilanceDepartement:
    """Vigilance courante (~24 h) pour un département."""

    departement: str
    update_time: pd.Timestamp  # UTC : émission de la carte
    fin_validite: pd.Timestamp | None  # UTC : fin de la période de validité
    phenomenes: list[VigilancePhenomene] = field(default_factory=list)

    @property
    def niveau_max_global(self) -> int:
        """Pire niveau, tous phénomènes confondus — pour décision bandeau."""
        if not self.phenomenes:
            return 1
        return max(p.niveau for p in self.phenomenes)


def _ts(epoch: object) -> pd.Timestamp | None:
    """Epoch (s) → Timestamp UTC, ``None`` si absent/illisible."""
    if not isinstance(epoch, (int, float, str)):
        return None
    try:
        return pd.Timestamp(int(epoch), unit="s", tz="UTC")
    except (TypeError, ValueError):
        return None


def recuperer_vigilance(
    departement: str = DEPARTEMENT_DEFAUT,
    token: str | None = None,
    timeout: float = 10.0,
    session: requests.Session | None = None,
) -> VigilanceDepartement | None:
    """Récupère et parse la Vigilance MF (webservice) pour un département.

    Parameters
    ----------
    departement :
        Code département à 2 chiffres (``"35"`` pour Ille-et-Vilaine).
    token :
        Token webservice MF. Par défaut : env ``METEOFRANCE_WS_TOKEN`` sinon la
        valeur publique connue (partagée avec ``meteofrance_officiel``).
    timeout :
        Délai max HTTP (secondes).
    session :
        Session requests injectable pour tests/mock.

    Returns
    -------
    VigilanceDepartement | None
        ``None`` si la requête échoue (le bloc Vigilance est alors omis —
        dégradation gracieuse, le mail part sans).
    """
    tok = token or os.environ.get(ENV_TOKEN, DEFAULT_TOKEN)
    sess = session or requests.Session()
    params = {"domain": departement, "depth": "0", "token": tok}
    try:
        resp = get_avec_retry(sess, WARNING_URL, params=params, timeout=timeout)
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Vigilance MF (webservice) : erreur fetch (%s)", e)
        return None
    return parser_vigilance(data, departement)


def parser_vigilance(
    data: dict,
    departement: str = DEPARTEMENT_DEFAUT,
) -> VigilanceDepartement | None:
    """Parse le JSON ``currentphenomenons`` du webservice MF.

    Format (vérifié) :

    .. code-block:: json

        {
          "update_time": 1780718405,
          "end_validity_time": 1780783200,
          "domain_id": "35",
          "phenomenons_max_colors": [
            {"phenomenon_id": "1", "phenomenon_max_color_id": 1}, ...
          ]
        }

    Les phénomènes absents de la réponse sont supposés verts (niveau 1).
    """
    if not isinstance(data, dict):
        return None
    par_phenom: dict[int, int] = dict.fromkeys(PHENOMENES_NOMS, 1)
    for item in data.get("phenomenons_max_colors") or []:
        try:
            pid = int(item.get("phenomenon_id"))
            niveau = int(item.get("phenomenon_max_color_id", 1))
        except (TypeError, ValueError):
            continue
        if pid in par_phenom and niveau in NIVEAU_NOMS:
            par_phenom[pid] = niveau

    update_time = _ts(data.get("update_time")) or pd.Timestamp.now(tz="UTC")
    phenomenes = [
        VigilancePhenomene(code=pid, nom=PHENOMENES_NOMS[pid], niveau=par_phenom[pid])
        for pid in PHENOMENES_PERTINENTS
    ]
    return VigilanceDepartement(
        departement=departement,
        update_time=update_time,
        fin_validite=_ts(data.get("end_validity_time")),
        phenomenes=phenomenes,
    )
