"""Client VigiEau — restrictions sécheresse en vigueur (situation courante).

Interroge l'API publique VigiEau (service de l'État, successeur de
Propluvia) pour connaître le **niveau de restriction d'usage de l'eau en
vigueur** sur une commune, par type de ressource (eau souterraine,
superficielle, potable). VigiEau ne sert que la **situation courante**
(pas d'historique profond).

Endpoint :
- ``GET /api/zones?commune=<insee>&profil=<profil>`` — liste des zones
  d'alerte applicables (vide = aucune restriction en vigueur).

Le ``profil`` cible l'usager : ``exploitation`` (agriculteur) renvoie les
règles applicables à l'irrigation. Réponse vide → ``niveau = "aucune"``,
ce qui est un *vrai* négatif (et l'état le plus fréquent hors étiage).

Dégradation gracieuse : toute erreur réseau/format renvoie ``None`` (le
bloc restrictions est alors omis du bulletin).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests

from ._http_retry import get_avec_retry

logger = logging.getLogger(__name__)

ZONES_URL = "https://api.vigieau.gouv.fr/api/zones"

# Pleine-Fougères (Ille-et-Vilaine) — code INSEE officiel.
COMMUNE_INSEE_PLEINE_FOUGERES = "35225"
PROFIL_DEFAUT = "exploitation"

# Niveaux de gravité VigiEau, du moins au plus sévère (sert au tri / au max).
ORDRE_GRAVITE: tuple[str, ...] = (
    "vigilance",
    "alerte",
    "alerte_renforcee",
    "crise",
)

NIVEAU_AUCUNE = "aucune"

LABELS_NIVEAU: dict[str, str] = {
    NIVEAU_AUCUNE: "Aucune restriction en vigueur",
    "vigilance": "Vigilance",
    "alerte": "Alerte",
    "alerte_renforcee": "Alerte renforcée",
    "crise": "Crise",
}

# Libellés des types de ressource VigiEau.
LABELS_TYPE: dict[str, str] = {
    "SOU": "Eaux souterraines (nappe)",
    "SUP": "Eaux superficielles (cours d'eau)",
    "AEP": "Eau potable",
}


@dataclass(frozen=True)
class UsageRestriction:
    """Un usage soumis à restriction (thématique Irriguer, pour exploitant)."""

    nom: str
    thematique: str
    description: str


@dataclass(frozen=True)
class ZoneRestriction:
    """Une zone d'alerte VigiEau applicable (par type de ressource)."""

    type_ressource: str  # "SOU" | "SUP" | "AEP"
    niveau: str  # clé de ORDRE_GRAVITE
    nom_zone: str
    usages_irrigation: tuple[UsageRestriction, ...] = field(default_factory=tuple)
    date_debut_arrete: str | None = None  # "YYYY-MM-DD" (dateDebutValidite arrêté)


@dataclass(frozen=True)
class RestrictionsEau:
    """Restrictions sécheresse en vigueur pour une commune (instant courant)."""

    commune_insee: str
    profil: str
    zones: list[ZoneRestriction] = field(default_factory=list)

    @property
    def niveau_max(self) -> str:
        """Niveau le plus sévère toutes ressources confondues."""
        if not self.zones:
            return NIVEAU_AUCUNE
        return max(self.zones, key=lambda z: ORDRE_GRAVITE.index(z.niveau)).niveau

    @property
    def niveau_max_label(self) -> str:
        return LABELS_NIVEAU.get(self.niveau_max, self.niveau_max)

    @property
    def niveau_souterrain(self) -> str:
        """Niveau pour les eaux *souterraines* (le plus pertinent pour un forage)."""
        sou = [z for z in self.zones if z.type_ressource == "SOU"]
        if not sou:
            return NIVEAU_AUCUNE
        return max(sou, key=lambda z: ORDRE_GRAVITE.index(z.niveau)).niveau


def _normaliser_niveau(brut: object) -> str | None:
    """Normalise un libellé de gravité VigiEau vers une clé de ORDRE_GRAVITE."""
    if not isinstance(brut, str):
        return None
    cle = brut.strip().lower().replace(" ", "_").replace("é", "e")
    return cle if cle in ORDRE_GRAVITE else None


def recuperer_restrictions(
    commune_insee: str = COMMUNE_INSEE_PLEINE_FOUGERES,
    profil: str = PROFIL_DEFAUT,
    timeout: float = 10.0,
    session: requests.Session | None = None,
) -> RestrictionsEau | None:
    """Récupère + parse les restrictions en vigueur, ``None`` si indispo."""
    sess = session or requests.Session()
    params = {"commune": commune_insee, "profil": profil}
    try:
        resp = get_avec_retry(sess, ZONES_URL, params=params, timeout=timeout)
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("VigiEau : erreur fetch commune=%s (%s)", commune_insee, e)
        return None
    return parser_restrictions(data, commune_insee=commune_insee, profil=profil)


def parser_restrictions(
    data: object,
    commune_insee: str = COMMUNE_INSEE_PLEINE_FOUGERES,
    profil: str = PROFIL_DEFAUT,
) -> RestrictionsEau | None:
    """Parse la liste de zones VigiEau. Liste vide = aucune restriction.

    Tolère un dict d'erreur (``{"statusCode": 404, ...}``) renvoyé par
    l'API quand il n'y a aucune zone : traité comme « aucune restriction ».
    """
    if isinstance(data, dict):
        # 404 « Aucune zone d'alerte en vigueur » → pas une erreur métier.
        if data.get("statusCode") == 404:
            return RestrictionsEau(commune_insee=commune_insee, profil=profil, zones=[])
        return None
    if not isinstance(data, list):
        return None

    zones: list[ZoneRestriction] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        niveau = _normaliser_niveau(item.get("niveauGravite"))
        if niveau is None:
            continue
        usages_bruts = item.get("usages") or []
        usages_irrigation: list[UsageRestriction] = []
        for u in usages_bruts:
            if not isinstance(u, dict):
                continue
            if not u.get("concerneExploitation"):
                continue
            thematique = str(u.get("thematique", ""))
            if thematique != "Irriguer":
                continue
            usages_irrigation.append(
                UsageRestriction(
                    nom=str(u.get("nom", "")),
                    thematique=thematique,
                    description=str(u.get("description", "")).strip(),
                )
            )
        arrete = item.get("arrete") or {}
        date_debut = arrete.get("dateDebutValidite") if isinstance(arrete, dict) else None
        zones.append(
            ZoneRestriction(
                type_ressource=str(item.get("type", "")).upper(),
                niveau=niveau,
                nom_zone=str(item.get("nom", "")),
                usages_irrigation=tuple(usages_irrigation),
                date_debut_arrete=str(date_debut) if date_debut else None,
            )
        )
    return RestrictionsEau(commune_insee=commune_insee, profil=profil, zones=zones)
