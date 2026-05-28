"""Génération de graphiques PNG embarqués dans le mail Veille.

Produit des chaînes ``data:image/png;base64,...`` prêtes à insérer
dans un ``<img src=...>``. Aucune dépendance UI Streamlit ; pure
matplotlib (backend ``Agg``).
"""

from __future__ import annotations

import base64
import io

import matplotlib

# Backend sans GUI — obligatoire en script / GH Actions.
matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

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
    ax_t.plot(df.index, t_c, color=COULEUR_T, linewidth=1.6)
    ax_t.fill_between(df.index, t_c, color=COULEUR_T, alpha=0.15)
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

    ax_p.xaxis.set_major_formatter(mdates.DateFormatter("%a %Hh", tz=df.index.tz))
    ax_p.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 6, 12, 18]))
    plt.setp(ax_p.xaxis.get_majorticklabels(), rotation=0, ha="center", fontsize=8)
    ax_p.grid(True, alpha=0.3)
    ax_p.set_xlabel("")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")
