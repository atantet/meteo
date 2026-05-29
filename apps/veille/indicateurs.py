"""Calcul des indicateurs météorologiques pour l'App 1 Veille.

À partir d'une prévision horaire (DataFrame indexé tz-aware UTC sortie
de ``meteo_socle.sources.openmeteo.OpenMeteoForecast``), calcule les
indicateurs envoyés dans l'email matinal :

- Température min / max sur les prochaines 24 h (proxy nuit / jour)
- Cumuls de pluie 24 / 48 / 72 h
- Vent moyen et rafales maximaux 24 h (km/h)
- ETP cumulée 24 h (caractère séchant du jour)
- Bilan eau (P − ETP) cumulé 7 jours
- Flag "tension irrigation" si l'heuristique config est déclenchée

**Cohérence inter-apps (cf. principe #4 rigueur scientifique)** :
l'ETP est calculée par ``meteo_socle.indices.etp_fao.calcul_etp``
(FAO Penman-Monteith horaire, ADR-0004), **pas** reprise du champ
``etp_open_meteo`` du fournisseur. Cela garantit la même méthode dans
toutes les apps (Veille, Opérationnelle, Climato) et nous donne la
maîtrise des hypothèses (R_so via pvlib, clearness, G jour/nuit).
``etp_open_meteo`` reste un cross-check possible mais n'est pas utilisé
en production.

Les seuils de la tension irrigation viennent de
``config["indicateurs"]["bilan_eau"]["tension_irrigation"]``.

Note v0 : la "nuit" et le "jour" sont approximés par "les prochaines
24 h" (le minimum atterrit naturellement en nuit, le maximum en
journée). Une discrimination plus fine (fenêtres horaires explicites)
peut être ajoutée en v1 si nécessaire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from meteo_socle.indices.etp_fao import calcul_etp
from meteo_socle.indices.mildiou import agreger_critere_journalier, smith_periods

# Conversions vers unités de présentation utilisateur.
KELVIN_OFFSET: float = 273.15
MS_TO_KMH: float = 3.6

# Colonnes d'entrée nécessaires au calcul d'ETP socle.
_INPUTS_ETP = [
    "temperature_2m",
    "humidite_relative",
    "vitesse_vent_10m",
    "rayonnement_global",
]

# Conversion direction (degrés) → secteur cardinal court.
CARDINAUX = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


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
    Retourne ``float("nan")`` si la colonne direction est absente.
    """
    if col_dir_deg not in df.columns or df[col_dir_deg].dropna().empty:
        return float("nan")
    rad = np.deg2rad(df[col_dir_deg])
    poids = df[col_vitesse] if (col_vitesse and col_vitesse in df.columns) else 1.0
    u = -poids * np.sin(rad)
    v = -poids * np.cos(rad)
    # Direction = angle "d'où vient le vent" — convention météo.
    return float(np.rad2deg(np.arctan2(-u.mean(), -v.mean())) % 360)


@dataclass
class IndicateursVeille:
    """Bundle des indicateurs calculés pour un envoi matinal."""

    temperature_min_24h_celsius: float
    temperature_max_24h_celsius: float

    cumul_pluie_24h_mm: float
    cumul_pluie_48h_mm: float
    cumul_pluie_72h_mm: float

    vent_max_24h_kmh: float
    rafales_max_24h_kmh: float
    direction_vent_dominante_deg: float
    direction_vent_dominante_cardinal: str

    etp_jour_mm: float
    bilan_eau_7j_mm: float

    prob_pluie_max_24h_pct: float
    prob_pluie_max_48h_pct: float
    prob_pluie_max_72h_pct: float

    tension_irrigation: bool

    # Mildiou Smith periods (cf. ADR-0007). Liste de dates locales sur
    # les 72 h à venir où une période de Smith est détectée.
    # Vide = pas de période ; len ≥ 1 = au moins une période sur la
    # fenêtre. Détail journalier (T_min, h HR ≥ seuil) inclus pour
    # transparence dans le mail.
    mildiou_smith_jours_a_risque: list[pd.Timestamp] = field(default_factory=list)
    mildiou_smith_detail: pd.DataFrame | None = None

    # Métadonnées prévision : 1er pas horaire effectivement utilisé après
    # filtrage ``now_utc`` (proxy "T+0" pour le mail).
    prevision_t0_utc: pd.Timestamp | None = None


def calculer_indicateurs(
    prevision: pd.DataFrame,
    now_utc: pd.Timestamp,
    config: dict[str, Any],
) -> IndicateursVeille:
    """Calcule les indicateurs Veille depuis une prévision horaire.

    Parameters
    ----------
    prevision :
        DataFrame indexé tz-aware UTC, colonnes selon les conventions
        socle (``temperature_2m`` K, ``precipitation`` mm,
        ``vitesse_vent_10m`` et ``rafales_vent_10m`` m/s,
        ``etp_open_meteo`` mm/h).
    now_utc :
        Référence temporelle. Les lignes du DataFrame antérieures sont
        ignorées.
    config :
        Configuration Veille (cf. ``apps.veille.config.load_config``).
        Seul ``indicateurs.bilan_eau.tension_irrigation`` est lu ici.

    Returns
    -------
    IndicateursVeille
        Dataclass groupant les valeurs synthétiques.

    Raises
    ------
    ValueError
        Si la prévision ne contient aucune heure ≥ ``now_utc``.
    """
    df = prevision.loc[prevision.index >= now_utc].copy()
    if df.empty:
        raise ValueError(
            "La prévision ne contient aucune heure ≥ now_utc — "
            "vérifier la fraîcheur du fetch Open-Meteo."
        )
    df = df.sort_index()

    h24 = df.head(24)
    h48 = df.head(48)
    h72 = df.head(72)
    h168 = df.head(24 * 7)

    temperature_celsius_24h = h24["temperature_2m"] - KELVIN_OFFSET

    # ETP via le socle FAO Penman-Monteith (cohérence inter-apps).
    site = config["site"]
    etp_horaire_24h = calcul_etp(
        h24[_INPUTS_ETP], site["latitude"], site["longitude"], site["altitude"]
    )
    etp_horaire_7j = calcul_etp(
        h168[_INPUTS_ETP], site["latitude"], site["longitude"], site["altitude"]
    )
    etp_24h = float(etp_horaire_24h.sum())
    pluie_24h = float(h24["precipitation"].sum())
    etp_7j = float(etp_horaire_7j.sum())
    pluie_7j = float(h168["precipitation"].sum())
    bilan_7j = pluie_7j - etp_7j

    tension_cfg = config["indicateurs"]["bilan_eau"]["tension_irrigation"]
    tension = (
        etp_24h > tension_cfg["seuil_etp_seche_mm"]
        and pluie_24h < tension_cfg["seuil_pluie_compense_mm"]
        and bilan_7j < tension_cfg["seuil_deficit_7j_mm"]
    )

    # Probabilité de pluie : colonne optionnelle (selon les variables
    # demandées dans le fetch). On donne 0 si absente.
    def _prob_max(window: pd.DataFrame) -> float:
        if "probabilite_pluie_pct" not in window.columns:
            return 0.0
        return float(window["probabilite_pluie_pct"].max())

    # Direction dominante sur 24h, pondérée par la vitesse.
    dir_deg = direction_dominante_vecteur(h24)
    dir_card = degrees_to_cardinal(dir_deg) if not np.isnan(dir_deg) else ""

    # Smith periods sur 72 h. Implémentation socle = ADR-0007.
    mildiou_cfg = config["indicateurs"].get("mildiou_smith", {"actif": False})
    smith_jours: list[pd.Timestamp] = []
    smith_detail: pd.DataFrame | None = None
    if mildiou_cfg.get("actif", False):
        tz_loc = site.get("tz", "Europe/Paris")
        # On agrège l'horizon 72 h. Ajoute la veille du premier jour
        # affiché (h≥now) si dispo dans la prévision, sinon le premier
        # jour ne pourra pas qualifier (par construction Smith demande
        # un jour A observable).
        h72_etendu = prevision.head(72 + 24).sort_index()
        critere = agreger_critere_journalier(
            h72_etendu,
            tz_locale=tz_loc,
            hr_seuil=float(mildiou_cfg.get("hr_seuil", 0.90)),
        )
        smith = smith_periods(
            critere,
            t_min_celsius=float(mildiou_cfg.get("t_min_celsius", 10.0)),
            heures_min=int(mildiou_cfg.get("heures_min", 11)),
        )
        # Bornes du jour local de "demain" inclus jusqu'à J+3.
        now_loc = now_utc.tz_convert(tz_loc)
        debut = (now_loc.normalize() + pd.Timedelta(days=1)).tz_localize(None)
        fin = (now_loc.normalize() + pd.Timedelta(days=3)).tz_localize(None)
        fenetre = critere.loc[debut:fin]
        smith_detail = fenetre.copy()
        smith_detail["smith_period"] = smith.reindex(fenetre.index, fill_value=False)
        smith_jours = list(smith_detail.index[smith_detail["smith_period"]])

    return IndicateursVeille(
        temperature_min_24h_celsius=float(temperature_celsius_24h.min()),
        temperature_max_24h_celsius=float(temperature_celsius_24h.max()),
        cumul_pluie_24h_mm=pluie_24h,
        cumul_pluie_48h_mm=float(h48["precipitation"].sum()),
        cumul_pluie_72h_mm=float(h72["precipitation"].sum()),
        vent_max_24h_kmh=float(h24["vitesse_vent_10m"].max() * MS_TO_KMH),
        rafales_max_24h_kmh=float(h24["rafales_vent_10m"].max() * MS_TO_KMH),
        direction_vent_dominante_deg=dir_deg if not np.isnan(dir_deg) else 0.0,
        direction_vent_dominante_cardinal=dir_card,
        etp_jour_mm=etp_24h,
        bilan_eau_7j_mm=bilan_7j,
        prob_pluie_max_24h_pct=_prob_max(h24),
        prob_pluie_max_48h_pct=_prob_max(h48),
        prob_pluie_max_72h_pct=_prob_max(h72),
        tension_irrigation=bool(tension),
        mildiou_smith_jours_a_risque=smith_jours,
        mildiou_smith_detail=smith_detail,
        prevision_t0_utc=df.index[0],
    )
