"""Client Vigilance Météo-France — API publique DPVigilance.

Récupère le niveau de vigilance officiel par département pour les 9
phénomènes de la Vigilance MF (vent violent, pluie-inondation, orages,
crues, neige-verglas, canicule, grand froid, avalanches,
vagues-submersion). Couverture J et J+1 (~48 h).

Authentification : OAuth 2.0 client_credentials avec ``application_id``
obtenu sur le portail https://portail-api.meteofrance.fr (souscription
à l'API "Données Publiques Vigilance" nécessaire).

Variable d'env : ``METEOFRANCE_TOKEN`` (chaîne base64 ``user:password``
fournie par le portail MF, sous "Application ID" — la même clé sert
pour toutes les APIs souscrites avec une même application). Si absente,
l'appel retourne ``None`` (mail envoyé sans bloc Vigilance, dégradé
gracieux).

Endpoint :
- ``GET /public/DPVigilance/v1/cartevigilance/encours`` — carte JSON
  des niveaux par département et phénomène pour J et J+1.

Le format de réponse parsé est volontairement simple : on extrait pour
un département donné le niveau max (J et J+1) de chaque phénomène
pertinent, et on expose une dataclass plate pour le rendu HTML.
"""

from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Endpoints publics MF.
TOKEN_URL = "https://portail-api.meteofrance.fr/token"
API_URL = "https://public-api.meteofrance.fr/public/DPVigilance/v1/cartevigilance/encours"

# Codes officiels MF des phénomènes Vigilance (cf. portail MF).
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

# Phénomènes pertinents pour Pleine-Fougères (35) maraîchage + blé.
# Crues exclues (Pleine-Fougères hors zone Couesnon inondable), avalanches
# et vagues-submersion sans objet à 15 km de la baie sur plateau. Cf.
# mémoire feedback "une-seule-methode-par-phenomene" et la décision
# d'archivage des seuils maison canicule/pluie/vent.
PHENOMENES_PERTINENTS: tuple[int, ...] = (1, 2, 3, 5, 6, 7)

# Couleurs Vigilance MF (1=vert .. 4=rouge).
NIVEAU_NOMS: dict[int, str] = {
    1: "Vert",
    2: "Jaune",
    3: "Orange",
    4: "Rouge",
}

# Code département par défaut.
DEPARTEMENT_DEFAUT = "35"

# Variable d'env pour le token MF (partagée avec les autres APIs MF —
# une seule application sur le portail = une seule clé pour tout).
ENV_APP_ID = "METEOFRANCE_TOKEN"


@dataclass
class VigilancePhenomene:
    """Niveau Vigilance pour un phénomène donné, J et J+1."""

    code: int  # 1..9
    nom: str  # libellé court FR
    niveau_j: int  # 1..4
    niveau_j1: int  # 1..4

    @property
    def niveau_max(self) -> int:
        """Pire des deux échéances — pour résumé compact."""
        return max(self.niveau_j, self.niveau_j1)


@dataclass
class VigilanceDepartement:
    """Vigilance complète pour un département à un instant donné."""

    departement: str
    update_time: pd.Timestamp  # UTC
    phenomenes: list[VigilancePhenomene]

    @property
    def niveau_max_global(self) -> int:
        """Pire niveau, tous phénomènes confondus — pour décision bandeau."""
        if not self.phenomenes:
            return 1
        return max(p.niveau_max for p in self.phenomenes)


def recuperer_vigilance(
    departement: str = DEPARTEMENT_DEFAUT,
    application_id: str | None = None,
    timeout: float = 10.0,
    session: requests.Session | None = None,
) -> VigilanceDepartement | None:
    """Récupère et parse la Vigilance MF pour un département.

    Parameters
    ----------
    departement :
        Code département à 2 chiffres (``"35"`` pour Ille-et-Vilaine).
    application_id :
        Clé API base64. Si ``None``, lue depuis l'env ``METEOFRANCE_TOKEN``.
    timeout :
        Délai max HTTP (secondes).
    session :
        Session requests injectable pour tests/mock.

    Returns
    -------
    VigilanceDepartement | None
        ``None`` si la clé API est absente ou si la requête échoue.
        L'absence ne casse pas le pipeline Veille (bloc skippé).
    """
    app_id = application_id or os.environ.get(ENV_APP_ID)
    if not app_id:
        logger.info(
            "Vigilance MF désactivée : %s absent de l'environnement. "
            "Configurer la clé API sur le portail MF pour activer.",
            ENV_APP_ID,
        )
        return None

    sess = session or requests.Session()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            token_resp = sess.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={"Authorization": "Basic " + app_id},
                timeout=timeout,
                verify=False,
                allow_redirects=False,
            )
        token_resp.raise_for_status()
        token = token_resp.json()["access_token"]
    except (requests.RequestException, KeyError, ValueError) as e:
        logger.warning("Vigilance MF : impossible d'obtenir un token (%s)", e)
        return None

    try:
        api_resp = sess.get(
            API_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout,
        )
        api_resp.raise_for_status()
        data = api_resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Vigilance MF : erreur fetch (%s)", e)
        return None

    return parser_vigilance(data, departement)


def parser_vigilance(
    data: dict,
    departement: str = DEPARTEMENT_DEFAUT,
) -> VigilanceDepartement | None:
    """Parse le JSON DPVigilance et extrait le département demandé.

    Format MF (simplifié) :

    .. code-block:: json

        {
          "product": {
            "update_time": "2026-05-31T16:00:00Z",
            "periods": [
              {
                "echeance": "J",
                "timelaps": {
                  "domain_ids": [
                    {
                      "domain_id": "35",
                      "phenomenon_items": [
                        {"phenomenon_id": "3", "phenomenon_max_color_id": 2},
                        ...
                      ]
                    }
                  ]
                }
              },
              {"echeance": "J1", ...}
            ]
          }
        }

    Si le département n'est pas trouvé, les niveaux retournés sont tous
    "vert" (1) — comportement défensif évitant les false alarms.
    """
    product = data.get("product") or {}
    update_time_str = product.get("update_time") or product.get("created_at")
    try:
        if update_time_str:
            update_time = pd.Timestamp(update_time_str).tz_convert("UTC")
        else:
            update_time = pd.Timestamp.now(tz="UTC")
    except (TypeError, ValueError):
        update_time = pd.Timestamp.now(tz="UTC")

    # par_phenom[code] = {"J": niveau, "J1": niveau}
    par_phenom: dict[int, dict[str, int]] = {pid: {"J": 1, "J1": 1} for pid in PHENOMENES_NOMS}

    for period in product.get("periods") or []:
        ech = str(period.get("echeance", "")).upper()
        if ech not in ("J", "J1"):
            continue
        timelaps = period.get("timelaps") or {}
        for dom in timelaps.get("domain_ids") or []:
            if str(dom.get("domain_id")) != departement:
                continue
            for phen in dom.get("phenomenon_items") or []:
                try:
                    pid = int(phen.get("phenomenon_id"))
                    niveau = int(phen.get("phenomenon_max_color_id", 1))
                except (TypeError, ValueError):
                    continue
                if pid in par_phenom and niveau in NIVEAU_NOMS:
                    par_phenom[pid][ech] = niveau

    phenomenes = [
        VigilancePhenomene(
            code=pid,
            nom=PHENOMENES_NOMS[pid],
            niveau_j=par_phenom[pid]["J"],
            niveau_j1=par_phenom[pid]["J1"],
        )
        for pid in PHENOMENES_PERTINENTS
    ]
    return VigilanceDepartement(
        departement=departement,
        update_time=update_time,
        phenomenes=phenomenes,
    )
