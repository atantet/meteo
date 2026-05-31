"""Cartes synoptiques pour le mail Veille — grille 3×2.

Récupère 6 cartes pour 3 échéances (T+0, T+24, T+48 par rapport au run
00 UTC du jour) :

- Colonne gauche : Met Office UK *surface pressure colour chart* —
  fronts dessinés (chauds/froids/occlus), isobares, pression marine.
  Vue Atlantique nord / Europe → contexte synoptique large.
- Colonne droite : Météociel AROME 1.3 km mode 24 *Résumé* —
  précipitations horaires + pression + nébulosité (+ neige/graupel).
  Vue France → détail spatial fin sur la zone.

Les 2 sources sont complémentaires : Met Office donne l'**origine**
(front), AROME donne le **détail spatial** (étendue, intensité).

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

# Échéances visées : T+0 (analyse), T+24, T+48 par rapport au run 00 UTC.
# AROME ech=0 n'est pas publié par Météociel → on prend ech=1 comme
# meilleure approximation de l'analyse (T+1h après le run = quasi-anal).
AROME_ECHEANCES = (1, 24, 48)
METOFFICE_ECHEANCES = (0, 24, 48)
LABELS_3 = ("Analyse 00 UTC", "Prévi +24 h", "Prévi +48 h")

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
    """Une carte prête à embarquer dans le mail."""

    label: str  # "Analyse 00 UTC", "Prévi +24 h", "Prévi +48 h"
    source: str  # "metoffice" | "arome"
    data_uri: str  # data:image/jpeg;base64,...  (vide si fetch échoué)


@dataclass
class CartesGrille:
    """Grille 3×2 complète + métadonnée run."""

    run_utc: pd.Timestamp  # run 00 UTC retenu
    metoffice: list[CarteSynoptique]  # 3 cartes (T+0, T+24, T+48)
    arome: list[CarteSynoptique]  # 3 cartes (T+1≈analyse, T+24, T+48)

    @property
    def nb_disponibles(self) -> int:
        return sum(1 for c in self.metoffice + self.arome if c.data_uri)


def _url_metoffice(run_utc: date, ech: int) -> str:
    """Met Office surface pressure chart pour run 00 UTC du jour et échéance ``ech``."""
    iso = f"{run_utc.isoformat()}T0000"
    return f"{METOFFICE_BASE}/{iso}/FSXX00T_{ech:02d}.gif"


def _url_arome(run_utc: date, ech: int) -> str:
    """Météociel AROME HD mode 24 pour run 00 UTC du jour et échéance ``ech``."""
    run_id = f"{run_utc.strftime('%Y%m%d')}00"
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
    """Récupère les 6 cartes pour le run 00 UTC du jour courant.

    Si le run 00 UTC du jour n'est pas encore publié (mail très matinal,
    par ex. avant 04 UTC), il faudra retomber sur la veille — non géré
    pour l'instant car le cron Veille tourne à 04:15 UTC, soit après
    publication. Le fallback j-1 reste une amélioration possible si
    besoin.

    Les fetches échoués retournent une carte avec ``data_uri=""`` ; le
    rendu mail saute silencieusement les cellules vides. L'absence de
    cartes ne casse pas l'envoi du mail.
    """
    if now_utc is None:
        now_utc = pd.Timestamp.now(tz="UTC")
    run_utc = now_utc.normalize()  # 00 UTC du jour
    run_date = run_utc.date()

    sess = session or requests.Session()
    metoffice: list[CarteSynoptique] = []
    arome: list[CarteSynoptique] = []

    for label, ech in zip(LABELS_3, METOFFICE_ECHEANCES, strict=True):
        url = _url_metoffice(run_date, ech)
        data_uri = _fetch_image(
            url,
            referer=METOFFICE_PAGE_AFFICHEE,
            largeur_max_px=largeur_max_px,
            timeout=timeout,
            session=sess,
        )
        metoffice.append(CarteSynoptique(label=label, source="metoffice", data_uri=data_uri))

    for label, ech in zip(LABELS_3, AROME_ECHEANCES, strict=True):
        url = _url_arome(run_date, ech)
        data_uri = _fetch_image(
            url,
            referer=METEOCIEL_PAGE_AFFICHEE,
            largeur_max_px=largeur_max_px,
            timeout=timeout,
            session=sess,
        )
        arome.append(CarteSynoptique(label=label, source="arome", data_uri=data_uri))

    return CartesGrille(run_utc=run_utc, metoffice=metoffice, arome=arome)
