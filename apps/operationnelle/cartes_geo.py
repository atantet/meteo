"""Cartes géographiques ARPEGE-Europe et ECMWF (résumé) pour l'App 2 §3.

Récupère 4 cartes ARPEGE-Europe Météociel sur les cibles J+1 / J+2 /
J+3 / J+4 (T+24, T+48, T+72, T+96 h) en mode 7 = « Résumé » (pression
au sol + précipitations + nébulosité). Permet de visualiser
spatialement le contexte synoptique à courte / moyenne échéance, en
complément de la grille tendance (variables ponctuelles).

Source ARPEGE : ``modeles7.meteociel.fr/modeles/arpege/run/YYYYMMDDHH/
arpegeeur-7-<ECH>.png``. Page humaine de référence :
``meteociel.fr/modeles/arpegee_cartes.php``.

ARPEGE-Europe horizon natif ~96 h (4 j), runs toutes les 6 h
(00 / 06 / 12 / 18 UTC). On prend le run le plus récent supposé
publié (latence Météociel ~5 h après l'init du run).

``recuperer_cartes_ecmwf`` fait de même pour ECMWF 0.25° (mode 36),
avec sa propre source (``modeles3.meteociel.fr/modeles/ecmwf2/runs/
YYYYMMDDHH/ecmwf-36-<ECH>.png``) et sa propre latence de publication
(~7 h 15, différente d'ARPEGE-Europe). Elle prend en paramètre des
**cibles UTC absolues** (pas des échéances relatives) : run ARPEGE et run
ECMWF n'étant pas les mêmes (latences différentes), viser « +72 h » depuis
chacun donnerait deux cibles décalées de plusieurs heures — glissant sur un
autre jour calendaire à l'affichage. Sert de comparaison visuelle côte à
côte avec ARPEGE — pas de fusion des deux, l'accord/désaccord reste à
l'appréciation du lecteur (jamais un indice de confiance calculé, cf.
décision explicite).

Chaque image est téléchargée, redimensionnée, ré-encodée en JPEG et
embarquée en ``data:`` base64 dans le rendu Streamlit — zéro hotlink,
même approche que `apps/veille/cartes_synoptiques.py`.
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass

import pandas as pd
import requests
from PIL import Image

from apps.shared.cartes_indispo import _motif_indispo

logger = logging.getLogger(__name__)

# Échéances cibles : J+1 / J+2 / J+3 / J+4 = T+24, T+48, T+72, T+96 h
# depuis le run. ARPEGE-Europe ne publie pas le T+0 dans cette
# présentation Météociel (mode 7) ; on couvre donc les 4 jours futurs.
ARPEGE_EUR_ECHEANCES = (24, 48, 72, 96)

# Mode Météociel ARPEGE-Europe. 7 = « Résumé » (pression au sol +
# précipitations + nébulosité — vue synthétique).
ARPEGE_EUR_MODE = 7

# Sous-domaine Météociel pour les archives (cohérent avec Veille).
METEOCIEL_BASE = "https://modeles7.meteociel.fr/modeles/arpege/run"

# Page humaine, fournie comme Referer (Météociel refuse parfois les
# requêtes sans Referer).
METEOCIEL_PAGE_AFFICHEE = "https://www.meteociel.fr/modeles/arpegee_cartes.php"

# Latence typique de publication d'un run sur Météociel : on retire
# 5 h à `now` puis on arrondit au cycle de 6 h le plus récent.
LATENCE_PUBLICATION_H = 5
CYCLE_RUN_H = 6

# ECMWF 0.25° résumé Météociel (mode 36 = « Résumé » sur ecmwf_ctrl.php).
# Sous-domaine et chemin distincts de l'ARPEGE-Europe (confirmés en direct) :
# https://modeles3.meteociel.fr/modeles/ecmwf2/runs/<run>/ecmwf-36-<ech>.png
ECMWF_MODE = 36
ECMWF_BASE = "https://modeles3.meteociel.fr/modeles/ecmwf2/runs"

# Page « humaine » interactive (Referer + lien affiché). Prend l'échéance en
# query string, contrairement à la page ARPEGE-Europe (statique).
ECMWF_PAGE_AFFICHEE = "https://www.meteociel.fr/modeles/ecmwf_ctrl.php"

# Latence de publication ECMWF 0.25° sur Météociel : run + 7 h 15 (page
# ecmwf_ctrl.php : « réactualisées à partir de 7h15, 13h15, 19h15 et 1h15 »
# pour les runs 00/06/12/18 UTC) — plus long que ARPEGE-Europe (5 h).
ECMWF_LATENCE_PUBLICATION_H = 7.25


@dataclass
class CarteGeo:
    """Une carte ARPEGE-Europe prête à embarquer.

    ``run_utc`` et ``cible_utc`` permettent au rendu d'afficher une
    légende explicite (« Cible : mer. 03/06 14 h · run lun. 01/06
    12 UTC »).
    """

    run_utc: pd.Timestamp
    cible_utc: pd.Timestamp
    echeance_h: int
    data_uri: str  # data:image/jpeg;base64,...  (vide si fetch échoué)
    motif_indispo: str = ""  # raison si data_uri vide (404/réseau…), pour le rendu


@dataclass
class CartesGeoSerie:
    """Série des 4 cartes ARPEGE-Europe (J+1 / J+2 / J+3 / J+4)."""

    cartes: list[CarteGeo]

    @property
    def nb_disponibles(self) -> int:
        return sum(1 for c in self.cartes if c.data_uri)


def _url_arpege_eur(run_utc: pd.Timestamp, ech: int) -> str:
    """URL Météociel ARPEGE-Europe résumé pour un run UTC et une échéance en h."""
    run_id = run_utc.strftime("%Y%m%d%H")
    return f"{METEOCIEL_BASE}/{run_id}/arpegeeur-{ARPEGE_EUR_MODE}-{ech}.png"


def _url_ecmwf(run_utc: pd.Timestamp, ech: int) -> str:
    """URL Météociel ECMWF 0.25° résumé pour un run UTC et une échéance en h."""
    run_id = run_utc.strftime("%Y%m%d%H")
    return f"{ECMWF_BASE}/{run_id}/ecmwf-{ECMWF_MODE}-{ech}.png?0"


def lien_ecmwf_ctrl(ech: int) -> str:
    """Lien Météociel interactif (``ecmwf_ctrl.php``) pour une échéance donnée.

    Contrairement à la page ARPEGE-Europe (statique), la page de contrôle
    ECMWF prend l'échéance en query string — on l'adapte donc par carte.
    """
    return f"{ECMWF_PAGE_AFFICHEE}?ech={ech}&mode={ECMWF_MODE}&carte=0&"


def _run_le_plus_recent(now_utc: pd.Timestamp) -> pd.Timestamp:
    """Dernier cycle de run (multiple de 6 h) supposé publié à ``now_utc``.

    On retire `LATENCE_PUBLICATION_H` heures pour tenir compte du
    temps de publication Météociel, puis on arrondit vers le bas au
    multiple de `CYCLE_RUN_H` heures.
    """
    candidat = now_utc - pd.Timedelta(hours=LATENCE_PUBLICATION_H)
    return candidat.floor(f"{CYCLE_RUN_H}h")


def _run_le_plus_recent_ecmwf(now_utc: pd.Timestamp) -> pd.Timestamp:
    """Dernier cycle de run ECMWF (multiple de 6 h) supposé publié à ``now_utc``.

    Même cycle que ARPEGE-Europe mais latence propre à ECMWF
    (``ECMWF_LATENCE_PUBLICATION_H``, plus longue).
    """
    candidat = now_utc - pd.Timedelta(hours=ECMWF_LATENCE_PUBLICATION_H)
    return candidat.floor(f"{CYCLE_RUN_H}h")


def _fetch_image(
    url: str,
    largeur_max_px: int,
    timeout: float,
    session: requests.Session,
    referer: str = METEOCIEL_PAGE_AFFICHEE,
    label: str = "ARPEGE-Europe",
) -> tuple[str, str]:
    """Télécharge, redimensionne, encode JPEG base64.

    Retourne ``(data_uri, motif)`` : ``motif`` vide si OK ; sinon ``data_uri``
    vide et ``motif`` = raison lisible de l'indisponibilité (pour l'afficher
    explicitement, jamais de carte qui disparaît en silence).
    """
    try:
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
        motif = _motif_indispo(e)
        logger.warning("Carte %s indisponible (%s) : %s — %s", label, url, e, motif)
        return "", motif

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
    return "data:image/jpeg;base64," + base64.b64encode(buf.read()).decode("ascii"), ""


def recuperer_cartes(
    now_utc: pd.Timestamp | None = None,
    largeur_max_px: int = 700,
    timeout: float = 10.0,
    session: requests.Session | None = None,
    echeances: tuple[int, ...] = ARPEGE_EUR_ECHEANCES,
) -> CartesGeoSerie:
    """Récupère les cartes ARPEGE-Europe aux ``echeances`` demandées (h).

    Choix du run **déterministe** (ADR-0011 D4) :

    - On vise le dernier multiple de 6 h `≤ now_utc - 5 h` (latence
      typique de publication Météociel). Pas de fallback runtime : si ce
      run échoue systématiquement à l'heure dite, on corrige la constante
      de latence.
    - Si un fetch échoue (réseau, plage hors archive), la carte concernée
      retourne ``data_uri=""`` + un ``motif_indispo`` lisible ; le rendu
      affiche alors une ligne explicite « carte indisponible (motif) »
      (jamais une absence muette).

    ``echeances`` permet de restreindre la série (défaut : les 4 cibles
    J+1→J+4). Le mail Veille n'en prend que les deux dernières (J+3 / J+4,
    soit T+72 / T+96) en prolongement des cartes synoptiques 48 h.
    """
    if now_utc is None:
        now_utc = pd.Timestamp.now(tz="UTC")

    run_choisi = _run_le_plus_recent(now_utc)

    sess = session or requests.Session()
    cartes: list[CarteGeo] = []
    for ech in echeances:
        url = _url_arpege_eur(run_choisi, ech)
        data_uri, motif = _fetch_image(
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
                motif_indispo=motif,
            )
        )

    return CartesGeoSerie(cartes=cartes)


def recuperer_cartes_ecmwf(
    cibles_utc: tuple[pd.Timestamp, ...],
    now_utc: pd.Timestamp | None = None,
    largeur_max_px: int = 700,
    timeout: float = 10.0,
    session: requests.Session | None = None,
) -> CartesGeoSerie:
    """Récupère les cartes ECMWF 0.25° Météociel aux ``cibles_utc`` demandées.

    Contrairement à :func:`recuperer_cartes` (ARPEGE-Europe, échéances fixes
    depuis son propre run), on vise ici des **cibles UTC absolues** — les
    mêmes que les cartes ARPEGE déjà récupérées (``c.cible_utc`` pour chaque
    carte de la série ARPEGE), pas les mêmes échéances relatives. Le run
    ECMWF choisi (latence propre, ``ECMWF_LATENCE_PUBLICATION_H`` > celle
    d'ARPEGE-Europe) n'est pas le même run qu'ARPEGE : viser « +72 h » depuis
    CE run décale la cible réelle de plusieurs heures et fait glisser
    l'affichage sur un autre jour calendaire — même principe de
    synchronisation que Met Office / AROME 48 h dans
    ``apps/veille/cartes_synoptiques.py``.

    ``echeance_h`` de chaque carte retournée est dérivée de ``cible - run``
    (peut différer de 72/96 selon l'écart de run avec ARPEGE, typiquement
    +0 à +12 h) : c'est attendu, la garantie porte sur ``cible_utc``, pas sur
    l'échéance affichée.
    """
    if now_utc is None:
        now_utc = pd.Timestamp.now(tz="UTC")

    run_choisi = _run_le_plus_recent_ecmwf(now_utc)

    sess = session or requests.Session()
    cartes: list[CarteGeo] = []
    for cible in cibles_utc:
        ech = int((cible - run_choisi).total_seconds() // 3600)
        url = _url_ecmwf(run_choisi, ech)
        data_uri, motif = _fetch_image(
            url,
            largeur_max_px=largeur_max_px,
            timeout=timeout,
            session=sess,
            referer=ECMWF_PAGE_AFFICHEE,
            label="ECMWF",
        )
        cartes.append(
            CarteGeo(
                run_utc=run_choisi,
                cible_utc=cible,
                echeance_h=ech,
                data_uri=data_uri,
                motif_indispo=motif,
            )
        )

    return CartesGeoSerie(cartes=cartes)
