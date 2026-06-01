"""Cartes géographiques 7 j ECMWF Météociel pour l'App 2 Opérationnelle (§3).

Récupère 4 cartes ECMWF déterministes (Météociel) sur les cibles
J+0 / J+2 / J+4 / J+6 (T+0, T+48, T+96, T+144). Permet de visualiser
spatialement la situation synoptique à moyenne échéance, en complément
de la grille tendance (variables ponctuelles) et des cartes Veille
(courte échéance Met Office + AROME).

Source : ``modeles/ecmwf/runs/YYYYMMDDHH/ECM<MAP>-<ECH>.GIF`` sur
``meteociel.fr``. Run de référence = 00 UTC du jour (rafraîchi vers
~08 h UTC sur Météociel). Si le run du jour n'est pas encore publié,
fallback vers le run 00 UTC de la veille.

Format de carte (param ``map``) :

- ``0`` : Carte Géopotentiel 500 hPa + pression au sol (vue Europe).
  Donne la circulation générale et les centres d'action.

Pourquoi ECMWF Météociel et pas Wetterzentrale ?

- Pattern d'URL stable et même CDN que Veille AROME.
- Cohérent avec le format d'archive utilisé par les autres apps.
- Pas d'authentification, pas de quota visible.

Chaque image est téléchargée, redimensionnée, ré-encodée en JPEG et
embarquée en ``data:`` base64 dans le rendu Streamlit (zéro hotlink,
robuste — même approche que `apps/veille/cartes_synoptiques.py`).
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass

import pandas as pd
import requests
from PIL import Image

logger = logging.getLogger(__name__)

# Échéances cibles : J+0 / J+2 / J+4 / J+6 = T+0, T+48, T+96, T+144 h
# depuis le run 00 UTC. Le pas 48 h colle bien à l'horizon ECMWF
# déterministe et donne 4 instantanés bien répartis sur la semaine.
ECMWF_ECHEANCES = (0, 48, 96, 144)

# Mode de carte Météociel ECMWF. 0 = Géopotentiel 500 hPa + pression
# au sol — la carte synoptique « standard » utile pour anticiper les
# régimes (zonal, blocage, NAO+ / NAO−).
ECMWF_MAP = 0

# Sous-domaine Météociel public (modeles7 disponible et utilisé par
# Veille AROME pour archives).
METEOCIEL_BASE = "https://www.meteociel.fr/modeles/ecmwf/runs"

# Page humaine, fournie comme Referer pour les requêtes (Météociel
# refuse parfois les requêtes sans Referer).
METEOCIEL_PAGE_AFFICHEE = "https://www.meteociel.fr/modeles/ecmwf.php"


@dataclass
class CarteGeo:
    """Une carte ECMWF prête à embarquer.

    ``run_utc`` et ``cible_utc`` permettent au rendu d'afficher une
    légende explicite (« Cible : mer. 03/06 02 h · run lun. 01/06
    02 h »).
    """

    run_utc: pd.Timestamp
    cible_utc: pd.Timestamp
    echeance_h: int
    data_uri: str  # data:image/jpeg;base64,...  (vide si fetch échoué)


@dataclass
class CartesGeoSerie:
    """Série des 4 cartes ECMWF (J+0 / J+2 / J+4 / J+6)."""

    cartes: list[CarteGeo]

    @property
    def nb_disponibles(self) -> int:
        return sum(1 for c in self.cartes if c.data_uri)


def _url_ecmwf(run_utc: pd.Timestamp, ech: int) -> str:
    """URL Météociel ECMWF pour un run UTC donné et une échéance en h."""
    run_id = run_utc.strftime("%Y%m%d%H")
    return f"{METEOCIEL_BASE}/{run_id}/ECM{ECMWF_MAP}-{ech}.GIF"


def _fetch_image(
    url: str,
    largeur_max_px: int,
    timeout: float,
    session: requests.Session,
) -> str:
    """Télécharge, redimensionne, encode JPEG base64. Retourne ``""`` si échec."""
    try:
        resp = session.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; meteo-pleinefougeres/1.0)",
                "Referer": METEOCIEL_PAGE_AFFICHEE,
            },
        )
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
    except (requests.RequestException, OSError) as e:
        logger.warning("Carte ECMWF indisponible (%s) : %s", url, e)
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
    img.save(buf, format="JPEG", quality=78, optimize=True)
    buf.seek(0)
    return "data:image/jpeg;base64," + base64.b64encode(buf.read()).decode("ascii")


def recuperer_cartes(
    now_utc: pd.Timestamp | None = None,
    largeur_max_px: int = 700,
    timeout: float = 10.0,
    session: requests.Session | None = None,
) -> CartesGeoSerie:
    """Récupère 4 cartes ECMWF aux cibles J+0 / J+2 / J+4 / J+6.

    Choix du run :

    - On vise le run **00 UTC du jour courant**. Météociel le publie
      typiquement à partir de ~08 UTC.
    - Si ``now_utc`` est avant 08 UTC OU si le run du jour échoue à
      la 1ʳᵉ requête (carte 404), on bascule sur le **run 00 UTC de
      la veille**. Pas plus de fallback — au-delà, mieux vaut signaler
      l'indispo à l'utilisateur.

    Les fetches échoués retournent une carte ``data_uri=""`` ; le rendu
    saute silencieusement les cellules vides.
    """
    if now_utc is None:
        now_utc = pd.Timestamp.now(tz="UTC")

    run_jour = now_utc.normalize()  # 00 UTC du jour
    run_veille = run_jour - pd.Timedelta(hours=24)
    # Bascule simple : avant 08 UTC, le run du jour n'est probablement
    # pas dispo, on prend la veille d'office.
    run_choisi = run_jour if now_utc.hour >= 8 else run_veille

    sess = session or requests.Session()
    cartes: list[CarteGeo] = []
    for i, ech in enumerate(ECMWF_ECHEANCES):
        url = _url_ecmwf(run_choisi, ech)
        data_uri = _fetch_image(
            url,
            largeur_max_px=largeur_max_px,
            timeout=timeout,
            session=sess,
        )
        # Fallback : si la 1ʳᵉ carte du run choisi échoue, on retombe
        # sur le run de la veille pour toutes les cartes restantes.
        if i == 0 and not data_uri and run_choisi == run_jour:
            run_choisi = run_veille
            url = _url_ecmwf(run_choisi, ech)
            data_uri = _fetch_image(
                url,
                largeur_max_px=largeur_max_px,
                timeout=timeout,
                session=sess,
            )
        cible = run_choisi + pd.Timedelta(hours=ech)
        cartes.append(
            CarteGeo(
                run_utc=run_choisi,
                cible_utc=cible,
                echeance_h=ech,
                data_uri=data_uri,
            )
        )

    return CartesGeoSerie(cartes=cartes)
