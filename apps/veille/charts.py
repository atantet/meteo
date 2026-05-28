"""Génération de graphiques PNG embarqués dans le mail Veille.

Produit des chaînes ``data:image/png;base64,...`` prêtes à insérer
dans un ``<img src=...>``. Aucune dépendance UI Streamlit ; pure
matplotlib (backend ``Agg``).
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

import matplotlib

# Backend sans GUI — obligatoire en script / GH Actions.
matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
from PIL import Image  # noqa: E402

logger = logging.getLogger(__name__)

# Référence climato (normale 2015-2024) — voir scripts/compute_normale_jour.py.
NORMALE_JOUR_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "climato" / "normale_jour_lapetiteclaye.csv"
)


def _charger_normale_t_moy() -> pd.Series | None:
    """Charge la normale T_moy par jour-de-l'année (1-366). ``None`` si absent."""
    if not NORMALE_JOUR_PATH.exists():
        logger.warning("Normale climato absente : %s", NORMALE_JOUR_PATH)
        return None
    try:
        df = pd.read_csv(NORMALE_JOUR_PATH)
        return df.set_index("day_of_year")["t_moy_celsius"]
    except (OSError, KeyError) as e:
        logger.warning("Normale climato illisible : %s", e)
        return None


# Analyse de surface DWD pour l'Atlantique nord / Europe — couvre la
# situation synoptique productive de la météo locale Bretagne. Image
# mise à jour 4 fois/jour (~00, 06, 12, 18 UTC).
DWD_SYNOPTIC_URL = (
    "https://www.dwd.de/DWD/wetter/wv_spez/hobbymet/wetterkarten/bwk_bodendruck_na_ana.png"
)

# Conversion socle vers présentation.
KELVIN_OFFSET: float = 273.15

# Couleurs alignées avec le HTML email.
COULEUR_T = "#c0392b"
COULEUR_PLUIE = "#3498db"
COULEUR_PROBA = "#16a085"


def graphique_72h_base64(
    prevision: pd.DataFrame,
    now_utc: pd.Timestamp,
    tz_locale: str = "Europe/Paris",
    horizon_h: int = 72,
) -> str:
    """Génère un PNG base64 du graph T° + pluie + proba sur ``horizon_h``.

    Parameters
    ----------
    prevision :
        DataFrame indexé UTC sorti de ``OpenMeteoForecast``.
    now_utc :
        Référence temporelle (filtre forward-only).
    tz_locale :
        Fuseau horaire pour les ticks de l'axe X.
    horizon_h :
        Nombre d'heures de prévision affichées (défaut 72).

    Returns
    -------
    str
        ``data:image/png;base64,...`` à insérer dans ``<img src=...>``.
        Si la prévision est vide, retourne une chaîne vide.
    """
    df = prevision.loc[prevision.index >= now_utc].head(horizon_h).copy()
    if df.empty:
        return ""
    df.index = df.index.tz_convert(tz_locale)

    fig, (ax_t, ax_p) = plt.subplots(
        2, 1, figsize=(7, 4), sharex=True, gridspec_kw={"height_ratios": [1, 1]}
    )

    # Bandeau T°.
    t_c = df["temperature_2m"] - KELVIN_OFFSET
    ax_t.plot(df.index, t_c, color=COULEUR_T, linewidth=1.6, label="Prévision")
    ax_t.fill_between(df.index, t_c, color=COULEUR_T, alpha=0.15)

    # Overlay climato T_moy par jour de l'année si disponible.
    normale = _charger_normale_t_moy()
    if normale is not None and not df.empty:
        doy = df.index.dayofyear
        normale_vals = normale.reindex(doy).values
        ax_t.plot(
            df.index,
            normale_vals,
            color="#7f8c8d",
            linestyle="--",
            linewidth=1.2,
            label="Normale 2015-2024",
        )
        ax_t.legend(loc="best", fontsize=7, frameon=False)

    ax_t.set_ylabel("T° (°C)", color=COULEUR_T)
    ax_t.tick_params(axis="y", labelcolor=COULEUR_T)
    ax_t.grid(True, alpha=0.3)
    ax_t.set_title(f"Prévision {horizon_h} h — Open-Meteo")

    # Pluie en barres + proba pluie en ligne (axe secondaire).
    if "precipitation" in df.columns:
        ax_p.bar(
            df.index,
            df["precipitation"],
            width=0.04,
            color=COULEUR_PLUIE,
            alpha=0.7,
            align="edge",
        )
        ax_p.set_ylabel("Pluie (mm/h)", color=COULEUR_PLUIE)
        ax_p.tick_params(axis="y", labelcolor=COULEUR_PLUIE)
        # La pluie est toujours ≥ 0 — borne basse à 0 pour éviter le
        # padding négatif de matplotlib.
        max_pluie = float(df["precipitation"].max()) if not df["precipitation"].empty else 0
        ax_p.set_ylim(bottom=0, top=max(max_pluie * 1.15, 1.0))
    if "probabilite_pluie_pct" in df.columns:
        ax_p2 = ax_p.twinx()
        ax_p2.plot(
            df.index,
            df["probabilite_pluie_pct"],
            color=COULEUR_PROBA,
            linewidth=1.5,
        )
        ax_p2.set_ylabel("Proba (%)", color=COULEUR_PROBA)
        ax_p2.tick_params(axis="y", labelcolor=COULEUR_PROBA)
        ax_p2.set_ylim(0, 100)

    # Ticks rotation 30° pour éviter le chevauchement, alignés à droite.
    ax_p.xaxis.set_major_formatter(mdates.DateFormatter("%a %Hh", tz=df.index.tz))
    ax_p.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 6, 12, 18]))
    plt.setp(ax_p.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)
    ax_p.grid(True, alpha=0.3)
    ax_p.set_xlabel("")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


def carte_synoptique_dwd_base64(
    url: str = DWD_SYNOPTIC_URL,
    largeur_max_px: int = 800,
    timeout: float = 10.0,
    session: requests.Session | None = None,
) -> str:
    """Récupère la dernière carte d'analyse synoptique DWD et la prépare pour mail.

    Télécharge l'image PNG (~5 MB), la redimensionne à ``largeur_max_px`` et
    la ré-encode en JPEG qualité 75 pour limiter la taille du mail à ~100-300 KB.

    Parameters
    ----------
    url :
        URL de l'image DWD. Par défaut, la *Bodendruckkarte* d'analyse
        pour l'Atlantique nord / Europe.
    largeur_max_px :
        Largeur cible en pixels (la hauteur suit le ratio d'origine).
    timeout :
        Délai max pour la requête HTTP (secondes).
    session :
        Session HTTP injectable pour tests (mock).

    Returns
    -------
    str
        ``data:image/jpeg;base64,...`` à insérer dans ``<img src=...>``.
        Chaîne vide en cas d'échec (réseau, image invalide). L'absence
        de carte ne doit pas casser l'envoi du mail.
    """
    sess = session or requests.Session()
    try:
        resp = sess.get(url, timeout=timeout)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
    except (requests.RequestException, OSError) as e:
        logger.warning("Carte synoptique DWD indisponible : %s", e)
        return ""

    # Aplatit éventuelle transparence RGBA → RGB pour JPEG.
    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Redimensionnement proportionnel.
    if img.width > largeur_max_px:
        hauteur = int(img.height * largeur_max_px / img.width)
        img = img.resize((largeur_max_px, hauteur), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75, optimize=True)
    buf.seek(0)
    return "data:image/jpeg;base64," + base64.b64encode(buf.read()).decode("ascii")
