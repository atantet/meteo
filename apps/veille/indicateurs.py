"""Calcul des indicateurs météorologiques pour l'App 1 Veille.

À partir de la **prévision officielle Météo-France** (DataFrame horaire indexé
tz-aware UTC, sortie de ``meteo_socle.sources.meteofrance_officiel``), calcule les
indicateurs envoyés dans l'e-mail. Cf. **ADR-0014**.

Changements ADR-0014 vs ADR-0011 :

- **Tout en heure locale** (``config["site"]["tz"]``), plus d'ancrage sur un run :
  la prévi MF est roulante. La fenêtre démarre à la **première période de 6 h
  entièrement couverte** par l'horaire et s'arrête à la **dernière période pleine**
  (``periodes_pleines``). On n'exploite que la **portion horaire** (``portion_horaire``).
- **Plus d'ETP** : la prévi MF ne fournit pas le rayonnement, et la Veille répond à
  « quel temps dans les prochaines ~48 h ? » (l'ETP/bilan est l'affaire de l'App 2).
- **Périodes 6 h locales** : Nuit 0-6 / Matin 6-12 / Après-midi 12-18 / Soir 18-24
  (labels honnêtes en heure locale).

Température : min/max sur 24 h et 48 h **sans découpage** pour les risques de gel
(min) et de canicule (max), à toute heure. **Exception** : le risque maladie
(« nuit douce ») utilise le min de la **nuit locale à venir** (J+1, [0, 6) locale),
``temperature_min_nuit_prochaine_celsius``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# Conversions vers unités de présentation utilisateur.
KELVIN_OFFSET: float = 273.15
MS_TO_KMH: float = 3.6

# Conversion direction (degrés) → secteur cardinal court.
CARDINAUX = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]

# Périodes de 6 h locales : heure de début → label (ADR-0014 D4).
LABEL_PAR_DEBUT: dict[int, str] = {0: "Nuit", 6: "Matin", 12: "Après-midi", 18: "Soir"}
PERIODE_H = 6


def degrees_to_cardinal(deg: float) -> str:
    """Convertit une direction (degrés, 0=N, 90=E) en secteur cardinal."""
    idx = int(round((deg % 360) / 45)) % 8
    return CARDINAUX[idx]


def direction_dominante_vecteur(
    df: pd.DataFrame,
    col_dir_deg: str = "direction_vent_deg",
    col_vitesse: str | None = "vitesse_vent_10m",
) -> float:
    """Direction dominante en degrés, par moyenne vectorielle pondérée vitesse.

    Si ``col_vitesse`` est ``None`` ou absente, pondération uniforme.
    Retourne ``float("nan")`` si la colonne direction est absente/vide.
    """
    if col_dir_deg not in df.columns or df[col_dir_deg].dropna().empty:
        return float("nan")
    rad = np.deg2rad(df[col_dir_deg])
    poids = df[col_vitesse] if (col_vitesse and col_vitesse in df.columns) else 1.0
    u = -poids * np.sin(rad)
    v = -poids * np.cos(rad)
    # Direction = angle "d'où vient le vent" — convention météo.
    return float(np.rad2deg(np.arctan2(-u.mean(), -v.mean())) % 360)


def moment_envoi(now_utc: pd.Timestamp, tz: str = "Europe/Paris") -> str:
    """Libellé du moment d'envoi : ``"matin"`` ou ``"après-midi"``.

    Déduit de l'**heure locale** (cron Veille 6 h 30 / 18 h 30 locale, ADR-0014
    D4) : avant midi local → matin, sinon après-midi.
    """
    heure_locale = now_utc.tz_convert(tz).hour
    return "matin" if heure_locale < 12 else "après-midi"


def portion_horaire(df: pd.DataFrame) -> pd.DataFrame:
    """Bloc de tête au **pas horaire** (1 h) de la prévi MF.

    La prévi MF est horaire puis passe à 3 h puis 6 h (ADR-0014). La Veille
    n'exploite que la portion horaire : on garde le préfixe contigu dont l'écart
    à l'échéance suivante est de 1 h (plus la dernière échéance de ce préfixe).
    """
    if len(df) <= 1:
        return df
    deltas = df.index.to_series().diff().shift(-1)  # écart vers l'échéance suivante
    une_heure = pd.Timedelta(hours=1)
    n = 0
    for d in deltas[:-1]:
        if d == une_heure:
            n += 1
        else:
            break
    return df.iloc[: n + 1]


def periodes_pleines(
    df_horaire_local: pd.DataFrame,
) -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    """Périodes de 6 h locales **entièrement couvertes** par l'horaire (ADR-0014 D4).

    ``df_horaire_local`` doit être indexé tz-aware en heure **locale**, au pas
    horaire (cf. ``portion_horaire``). Une période ``[début ; début+6 h[`` (alignée
    sur 0/6/12/18 locale) est retenue ssi **ses 6 heures rondes sont toutes
    présentes**. On découpe ainsi sur les périodes pleines, jamais sur l'heure
    d'envoi : la première période partielle (queue d'heures déjà écoulées) est
    exclue, la dernière partielle (au-delà de l'horaire) aussi.

    Returns
    -------
    list[(label, début_local, fin_local)]
        Triées chronologiquement (label ∈ Nuit/Matin/Après-midi/Soir).
    """
    if df_horaire_local.empty:
        return []
    heures_presentes = set(df_horaire_local.index)
    debut_jour = df_horaire_local.index.min().normalize()
    fin = df_horaire_local.index.max()
    out: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []
    p = debut_jour
    pas = pd.Timedelta(hours=PERIODE_H)
    while p <= fin:
        heures = [p + pd.Timedelta(hours=k) for k in range(PERIODE_H)]
        if all(h in heures_presentes for h in heures):
            out.append((LABEL_PAR_DEBUT[p.hour], p, p + pas))
        p = p + pas
    return out


@dataclass
class IndicateursVeille:
    """Bundle des indicateurs calculés pour un envoi (ADR-0014, sans ETP)."""

    temperature_min_24h_celsius: float
    temperature_max_24h_celsius: float
    temperature_min_48h_celsius: float
    temperature_max_48h_celsius: float

    cumul_pluie_24h_mm: float
    cumul_pluie_48h_mm: float

    vent_max_24h_kmh: float
    rafales_max_24h_kmh: float
    direction_vent_dominante_deg: float
    direction_vent_dominante_cardinal: str

    prob_pluie_max_24h_pct: float
    prob_pluie_max_48h_pct: float

    # Min de température sur la nuit locale À VENIR (J+1, [0, 6) locale), pour
    # l'alerte risque_maladies. NaN si la prévision ne couvre pas cette nuit.
    temperature_min_nuit_prochaine_celsius: float = float("nan")

    # 1ʳᵉ période de 6 h locale affichée (début) — proxy "T+0" du mail.
    prevision_t0_local: pd.Timestamp | None = None


def calculer_indicateurs(
    prevision: pd.DataFrame,
    now_utc: pd.Timestamp,
    config: dict[str, Any],
) -> IndicateursVeille:
    """Calcule les indicateurs Veille depuis la prévi horaire MF.

    Parameters
    ----------
    prevision :
        DataFrame indexé tz-aware UTC, colonnes socle (``temperature_2m`` K,
        ``precipitation`` mm, ``vitesse_vent_10m``/``rafales_vent_10m`` m/s,
        ``probabilite_pluie_pct`` %, ``direction_vent_deg``).
    now_utc :
        Référence temporelle (tz-aware UTC).
    config :
        Configuration Veille ; ``config["site"]["tz"]`` donne le fuseau local.

    Returns
    -------
    IndicateursVeille

    Raises
    ------
    ValueError
        Si aucune période de 6 h pleine n'est disponible.
    """
    tz = config["site"]["tz"]
    df = prevision.sort_index().copy()
    df.index = df.index.tz_convert(tz)

    # Portion horaire seule (ADR-0014 D4), puis fenêtre = première période pleine.
    df_h = portion_horaire(df)
    periodes = periodes_pleines(df_h)
    if not periodes:
        raise ValueError(
            "Aucune période de 6 h pleine dans la prévi MF — vérifier la fraîcheur du fetch."
        )
    debut = periodes[0][1]
    df_win = df_h.loc[df_h.index >= debut]

    h24 = df_win.head(24)
    h48 = df_win.head(48)

    temperature_celsius_24h = h24["temperature_2m"] - KELVIN_OFFSET
    temperature_celsius_48h = h48["temperature_2m"] - KELVIN_OFFSET

    # Min de la nuit locale À VENIR (J+1, [0, 6) locale) — risque maladie.
    jour_j1 = now_utc.tz_convert(tz).normalize() + pd.Timedelta(days=1)
    masque_nuit = (df.index.normalize() == jour_j1) & (df.index.hour >= 0) & (df.index.hour < 6)
    t_nuit_celsius = df.loc[masque_nuit, "temperature_2m"] - KELVIN_OFFSET
    t_min_nuit_prochaine = float(t_nuit_celsius.min()) if not t_nuit_celsius.empty else float("nan")

    def _prob_max(window: pd.DataFrame) -> float:
        if "probabilite_pluie_pct" not in window.columns:
            return 0.0
        valeurs = window["probabilite_pluie_pct"].dropna()
        return float(valeurs.max()) if not valeurs.empty else 0.0

    dir_deg = direction_dominante_vecteur(h24)
    dir_card = degrees_to_cardinal(dir_deg) if not np.isnan(dir_deg) else ""

    return IndicateursVeille(
        temperature_min_24h_celsius=float(temperature_celsius_24h.min()),
        temperature_max_24h_celsius=float(temperature_celsius_24h.max()),
        temperature_min_48h_celsius=float(temperature_celsius_48h.min()),
        temperature_max_48h_celsius=float(temperature_celsius_48h.max()),
        temperature_min_nuit_prochaine_celsius=t_min_nuit_prochaine,
        cumul_pluie_24h_mm=float(h24["precipitation"].sum()),
        cumul_pluie_48h_mm=float(h48["precipitation"].sum()),
        vent_max_24h_kmh=float(h24["vitesse_vent_10m"].max() * MS_TO_KMH),
        rafales_max_24h_kmh=float(h24["rafales_vent_10m"].max() * MS_TO_KMH),
        direction_vent_dominante_deg=dir_deg if not np.isnan(dir_deg) else 0.0,
        direction_vent_dominante_cardinal=dir_card,
        prob_pluie_max_24h_pct=_prob_max(h24),
        prob_pluie_max_48h_pct=_prob_max(h48),
        prevision_t0_local=df_win.index[0],
    )
