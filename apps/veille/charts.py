"""Génération de graphiques PNG embarqués dans le mail Veille.

Produit des chaînes ``data:image/png;base64,...`` prêtes à insérer
dans un ``<img src=...>``. Aucune dépendance UI Streamlit ; pure
matplotlib (backend ``Agg``).
"""

from __future__ import annotations

import base64
import io
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import matplotlib

# Backend sans GUI — obligatoire en script / GH Actions.
matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from PIL import Image  # noqa: E402

from .indicateurs import ancre_fenetre  # noqa: E402

# Abréviations FR pour l'axe X du graphique 48h — évite la dépendance
# à ``locale.setlocale("fr_FR.UTF-8")`` (souvent absent en CI / containers).
_JOURS_FR_COURT = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

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


def _charger_normale_hr() -> pd.Series | None:
    """Charge la normale HR_moy (%) par jour-de-l'année (1-366). ``None`` si absent."""
    if not NORMALE_JOUR_PATH.exists():
        return None
    try:
        df = pd.read_csv(NORMALE_JOUR_PATH)
        if "hr_moy_pct" not in df.columns:
            return None
        return df.set_index("day_of_year")["hr_moy_pct"]
    except (OSError, KeyError) as e:
        logger.warning("Normale HR illisible : %s", e)
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
# Palette Bang Wong 2011 (Nature Methods) — distinguable par
# daltoniens (deutéranopie, protanopie).
COULEUR_T = "#D55E00"  # vermillon — anomalie chaude
COULEUR_T_FROID = "#0072B2"  # bleu profond — anomalie froide
COULEUR_PLUIE = "#56B4E9"  # bleu ciel
COULEUR_PROBA = "#009E73"  # vert bleuté
COULEUR_HR = "#CC79A7"  # rose-violet — humidité relative
COULEUR_NORMALE = "#7f8c8d"  # gris neutre pour la ligne climato


def graphique_48h_base64(
    prevision: pd.DataFrame,
    now_utc: pd.Timestamp,
    tz_locale: str = "Europe/Paris",
    horizon_h: int = 48,
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
        Nombre d'heures de prévision affichées (défaut 48 — horizon
        natif AROME France HD).

    Returns
    -------
    str
        ``data:image/png;base64,...`` à insérer dans ``<img src=...>``.
        Si la prévision est vide, retourne une chaîne vide.
    """
    # Fenêtre ancrée sur la dernière demi-journée locale (00 h le matin,
    # 12 h l'après-midi — cf. ``ancre_fenetre``), alignée sur le tableau
    # Tendance et le libellé du mail. La prévision inclut ``past_days=1``
    # pour couvrir la portion ancre → T+0 de la demi-journée courante.
    x_min = ancre_fenetre(now_utc, tz_locale).tz_convert(tz_locale)
    x_max = x_min + pd.Timedelta(hours=horizon_h)

    prev_loc = prevision.copy()
    prev_loc.index = prev_loc.index.tz_convert(tz_locale)
    df = prev_loc.loc[(prev_loc.index >= x_min) & (prev_loc.index < x_max)].copy()
    if df.empty:
        return ""

    fig, (ax_t, ax_p, ax_hr) = plt.subplots(
        3,
        1,
        figsize=(7, 6),
        sharex=True,
        gridspec_kw={"height_ratios": [1.1, 1, 0.9]},
    )

    # Bandeau T° : courbe de prévision + remplissage entre prévi et
    # normale climato (rouge si au-dessus, bleu si en-dessous). Si la
    # normale n'est pas disponible, fallback sur fill jusqu'à la borne
    # basse (comportement v1).
    t_c = df["temperature_2m"] - KELVIN_OFFSET
    ax_t.plot(df.index, t_c, color=COULEUR_T, linewidth=1.6, label="Prévision")

    normale = _charger_normale_t_moy()
    if normale is not None and not df.empty:
        doy = df.index.dayofyear
        normale_vals = normale.reindex(doy).values
        ax_t.plot(
            df.index,
            normale_vals,
            color=COULEUR_NORMALE,
            linestyle="--",
            linewidth=1.2,
            label="Normale 1991-2020",
        )
        ax_t.fill_between(
            df.index,
            t_c.values,
            normale_vals,
            where=t_c.values >= normale_vals,
            color=COULEUR_T,
            alpha=0.18,
            interpolate=True,
        )
        ax_t.fill_between(
            df.index,
            t_c.values,
            normale_vals,
            where=t_c.values < normale_vals,
            color=COULEUR_T_FROID,
            alpha=0.18,
            interpolate=True,
        )
        ax_t.legend(loc="best", fontsize=7, frameon=False)
    else:
        ax_t.fill_between(df.index, t_c, color=COULEUR_T, alpha=0.15)

    ax_t.set_ylabel("T° (°C)", color=COULEUR_T)
    ax_t.tick_params(axis="y", labelcolor=COULEUR_T)
    ax_t.grid(True, alpha=0.3)
    ax_t.set_title(f"Prévision {horizon_h} h — Open-Meteo AROME France HD")

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

    ax_p.grid(True, alpha=0.3)
    ax_p.set_xlabel("")

    # Bandeau HR — 3e subplot, même logique de shading vs normale que la T°.
    if "humidite_relative" in df.columns:
        hr_pct = df["humidite_relative"] * 100
        ax_hr.plot(df.index, hr_pct, color=COULEUR_HR, linewidth=1.6, label="Prévision")
        normale_hr = _charger_normale_hr()
        if normale_hr is not None:
            doy_hr = df.index.dayofyear
            normale_hr_vals = normale_hr.reindex(doy_hr).values
            ax_hr.plot(
                df.index,
                normale_hr_vals,
                color=COULEUR_NORMALE,
                linestyle="--",
                linewidth=1.2,
                label="Normale 1991-2020",
            )
            ax_hr.fill_between(
                df.index,
                hr_pct.values,
                normale_hr_vals,
                where=hr_pct.values >= normale_hr_vals,
                color=COULEUR_HR,
                alpha=0.18,
                interpolate=True,
            )
            ax_hr.fill_between(
                df.index,
                hr_pct.values,
                normale_hr_vals,
                where=hr_pct.values < normale_hr_vals,
                color=COULEUR_T,
                alpha=0.18,
                interpolate=True,
            )
            ax_hr.legend(loc="best", fontsize=7, frameon=False)
        else:
            # Fallback : remplissage simple jusqu'à 0 si la normale HR
            # n'est pas (encore) calculée dans le CSV climato.
            ax_hr.fill_between(df.index, hr_pct, 0, color=COULEUR_HR, alpha=0.12)
        # Ligne repère 90 % = humectation foliaire (contexte maladies ;
        # n'est plus un critère d'alerte, cf. alertes.py risque_maladies).
        ax_hr.axhline(y=90, color=COULEUR_HR, linestyle=":", linewidth=0.8, alpha=0.6)
        ax_hr.set_ylabel("HR (%)", color=COULEUR_HR)
        ax_hr.tick_params(axis="y", labelcolor=COULEUR_HR)
        ax_hr.set_ylim(0, 100)
    ax_hr.grid(True, alpha=0.3)

    # Ticks X formatés FR ("Lun 13h"), appliqués au dernier axe partagé.
    def _fmt_x_fr(x: float, _pos: int) -> str:
        dt = mdates.num2date(x, tz=df.index.tz)
        return f"{_JOURS_FR_COURT[dt.weekday()]} {dt.hour}h"

    ax_hr.xaxis.set_major_formatter(FuncFormatter(_fmt_x_fr))
    ax_hr.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 6, 12, 18]))
    plt.setp(ax_hr.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)

    # Bornes axe X fixées sur la fenêtre [J0 00 h 00 ; J0+horizon],
    # alignées avec le tableau Tendance et le libellé du mail.
    ax_t.set_xlim(x_min, x_max)
    ax_p.set_xlim(x_min, x_max)
    ax_hr.set_xlim(x_min, x_max)

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
) -> tuple[str, datetime | None]:
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
    tuple[str, datetime | None]
        ``(data:image/jpeg;base64,..., last_modified_utc)``. La date est
        parsée depuis le header HTTP ``Last-Modified`` (= heure de
        production de l'analyse côté DWD), ``None`` si absent ou
        illisible. En cas d'échec réseau, retourne ``("", None)``.
        L'absence de carte ne doit pas casser l'envoi du mail.
    """
    sess = session or requests.Session()
    try:
        resp = sess.get(url, timeout=timeout)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
    except (requests.RequestException, OSError) as e:
        logger.warning("Carte synoptique DWD indisponible : %s", e)
        return "", None

    last_modified: datetime | None = None
    lm_header = resp.headers.get("Last-Modified")
    if lm_header:
        try:
            last_modified = parsedate_to_datetime(lm_header)
        except (TypeError, ValueError):
            last_modified = None

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
    data_uri = "data:image/jpeg;base64," + base64.b64encode(buf.read()).decode("ascii")
    return data_uri, last_modified
