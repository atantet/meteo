"""Cartes synoptiques pour le mail Veille — 2 sources, 4 cibles synchronisées.

Récupère 8 cartes pour le mail matinal, organisées en 4 paires
synchrones (mêmes cibles UTC pour MetOffice et AROME) :

- **00 UTC J** = ~02 h locale aujourd'hui (matin tôt)
- **12 UTC J** = ~14 h locale aujourd'hui (début d'après-midi)
- **00 UTC J+1** = ~02 h locale demain
- **12 UTC J+1** = ~14 h locale demain

Sources :

- **Met Office UK** *surface pressure colour chart* — run **00 UTC du
  jour**, échéances T+0 / T+12 / T+24 / T+36. Fronts dessinés
  (chauds/froids/occlus), isobares, pression marine. Vue Atlantique
  nord / Europe → contexte synoptique large.
- **Météociel AROME 1.3 km** mode 24 *Résumé* — run **18 UTC de la
  veille**, échéances T+6 / T+18 / T+30 / T+42 (alignées exactement
  sur les mêmes cibles UTC que MetOffice). Précipitations horaires +
  pression + nébulosité (+ neige/graupel). Vue France → détail spatial
  fin.

Pourquoi des runs différents ? Diagnostic 2026-06-01 :

- Met Office archive uniquement le run en cours (les précédents sont
  supprimés). Le run 00 UTC est publié progressivement ; T+48 arrive
  seulement après ~05 UTC. Donc on cale le cron Veille à 05:30 UTC.
  On s'arrête à T+36 (12 UTC J+1) ; T+48 (00 UTC J+2) ne serait pas
  synchronisable côté AROME (horizon max T+51 sur run 18 UTC veille).
- Météociel archive le run AROME 00 UTC bien après 05:30 UTC
  (≥ 08 UTC observé empiriquement). Le run 18 UTC de la veille est
  toujours dispo à 05:30 UTC.

Les 2 sources restent complémentaires : Met Office donne l'**origine**
(front), AROME donne le **détail spatial** (étendue, intensité). Le
fait qu'elles partagent exactement les mêmes 4 cibles facilite la
comparaison visuelle ligne à ligne.

Chaque image est téléchargée, redimensionnée, ré-encodée en JPEG et
embarquée en ``data:`` base64 dans le mail (zéro hotlink, robuste).
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd
import requests
from PIL import Image

logger = logging.getLogger(__name__)

# Met Office : run 00 UTC, échéances T+0 / T+12 / T+24 / T+36
# = cibles 00Z J / 12Z J / 00Z J+1 / 12Z J+1. Met Office produit en
# pas de 12 h (T+6, T+18, etc. n'existent pas pour ce produit).
METOFFICE_ECHEANCES = (0, 12, 24, 36)

# AROME : run 18 UTC de la veille (dispo dès 05:30 UTC contrairement
# au run 00 UTC du jour, qui n'arrive sur Météociel que vers 08 UTC).
# Échéances décalées de +6 h pour viser les mêmes cibles que MetOffice :
# - T+6  = 00 UTC J   (≡ MetOffice T+0)
# - T+18 = 12 UTC J   (≡ MetOffice T+12)
# - T+30 = 00 UTC J+1 (≡ MetOffice T+24)
# - T+42 = 12 UTC J+1 (≡ MetOffice T+36)
# Horizon max AROME 18Z veille = T+51, donc on s'arrête à T+42 par
# choix de synchro (impossible de matcher MetOffice T+48 sans T+54).
AROME_ECHEANCES = (6, 18, 30, 42)

# Sous-domaine Météociel (round-robin entre modeles[0-7]).
METEOCIEL_BASE = "https://modeles7.meteociel.fr/modeles/arome/archives"
# Mode 24 = "Résumé" (précipitations + pression + nébulosité). Map 0 = France.
AROME_MODE = 24
AROME_MAP = 0

# Met Office "surface pressure colour chart" — vue Atlantique nord / Europe.
METOFFICE_BASE = "https://data.consumer-digital.api.metoffice.gov.uk/v1/surface-pressure/colour"

# URLs publiques affichées en légende (page de consultation humaine).
METEOCIEL_PAGE_AFFICHEE = "https://www.meteociel.fr/modeles/arome.php"
METOFFICE_PAGE_AFFICHEE = "https://weather.metoffice.gov.uk/maps-and-charts/surface-pressure"


@dataclass
class CarteSynoptique:
    """Une carte prête à embarquer dans le mail.

    ``run_utc`` et ``cible_utc`` permettent à l'appelant (rendu mail)
    de formater des légendes explicites du type "Cible : mar. 02/06
    08 h · run dim. 31/05 20 h" — l'utilisateur sait toujours de quand
    date la prévi et pour quelle heure elle vaut.
    """

    source: str  # "metoffice" | "arome"
    run_utc: pd.Timestamp  # heure du run dont vient cette carte (tz UTC)
    cible_utc: pd.Timestamp  # heure de validité de la prévision (tz UTC)
    data_uri: str  # data:image/jpeg;base64,...  (vide si fetch échoué)


@dataclass
class CartesGrille:
    """Deux séries de 3 cartes : Met Office puis AROME.

    Pas de ``run_utc`` global : Met Office et AROME utilisent des runs
    différents (00 UTC jour vs 18 UTC veille). Chaque carte porte son
    propre run.
    """

    metoffice: list[CarteSynoptique]
    arome: list[CarteSynoptique]

    @property
    def nb_disponibles(self) -> int:
        return sum(1 for c in self.metoffice + self.arome if c.data_uri)


def _url_metoffice(run_date: date, ech: int) -> str:
    """Met Office surface pressure chart pour run 00 UTC du jour et échéance ``ech``."""
    iso = f"{run_date.isoformat()}T0000"
    return f"{METOFFICE_BASE}/{iso}/FSXX00T_{ech:02d}.gif"


def _url_arome(run_utc: pd.Timestamp, ech: int) -> str:
    """Météociel AROME HD mode 24 pour un run UTC quelconque (00 ou 18) et échéance ``ech``."""
    run_id = run_utc.strftime("%Y%m%d%H")
    return f"{METEOCIEL_BASE}/{run_id}/arome-{AROME_MODE}-{ech}-{AROME_MAP}.png"


def _fetch_image(
    url: str,
    referer: str,
    largeur_max_px: int,
    timeout: float,
    session: requests.Session,
) -> str:
    """Télécharge, redimensionne, encode JPEG base64. Retourne ``""`` si échec."""
    try:
        # Referer aide chez Météociel (page consommatrice attendue).
        resp = session.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; meteo-pleinefougeres/1.0)",
                "Referer": referer,
            },
        )
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
    except (requests.RequestException, OSError) as e:
        logger.warning("Carte indisponible (%s) : %s", url, e)
        return ""

    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    if img.width > largeur_max_px:
        hauteur = int(img.height * largeur_max_px / img.width)
        img = img.resize((largeur_max_px, hauteur), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75, optimize=True)
    buf.seek(0)
    return "data:image/jpeg;base64," + base64.b64encode(buf.read()).decode("ascii")


def recuperer_cartes(
    now_utc: pd.Timestamp | None = None,
    largeur_max_px: int = 520,
    timeout: float = 10.0,
    session: requests.Session | None = None,
) -> CartesGrille:
    """Récupère les 6 cartes pour les runs configurés.

    - Met Office : run 00 UTC du jour courant (T+0 / T+24 / T+48).
    - AROME : run 18 UTC de la veille (T+12 / T+30 / T+48).

    Les fetches échoués retournent une carte avec ``data_uri=""`` ; le
    rendu mail saute silencieusement les cellules vides. L'absence de
    cartes ne casse pas l'envoi du mail.
    """
    if now_utc is None:
        now_utc = pd.Timestamp.now(tz="UTC")

    run_metoffice = now_utc.normalize()  # 00 UTC du jour
    run_arome = run_metoffice - pd.Timedelta(hours=6)  # 18 UTC veille

    sess = session or requests.Session()
    metoffice: list[CarteSynoptique] = []
    arome: list[CarteSynoptique] = []

    for ech in METOFFICE_ECHEANCES:
        url = _url_metoffice(run_metoffice.date(), ech)
        data_uri = _fetch_image(
            url,
            referer=METOFFICE_PAGE_AFFICHEE,
            largeur_max_px=largeur_max_px,
            timeout=timeout,
            session=sess,
        )
        cible = run_metoffice + pd.Timedelta(hours=ech)
        metoffice.append(
            CarteSynoptique(
                source="metoffice",
                run_utc=run_metoffice,
                cible_utc=cible,
                data_uri=data_uri,
            )
        )

    for ech in AROME_ECHEANCES:
        url = _url_arome(run_arome, ech)
        data_uri = _fetch_image(
            url,
            referer=METEOCIEL_PAGE_AFFICHEE,
            largeur_max_px=largeur_max_px,
            timeout=timeout,
            session=sess,
        )
        cible = run_arome + pd.Timedelta(hours=ech)
        arome.append(
            CarteSynoptique(
                source="arome",
                run_utc=run_arome,
                cible_utc=cible,
                data_uri=data_uri,
            )
        )

    return CartesGrille(metoffice=metoffice, arome=arome)
