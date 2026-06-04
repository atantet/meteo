"""Calcul des indicateurs météorologiques pour l'App 1 Veille.

À partir d'une prévision horaire (DataFrame indexé tz-aware UTC sortie
de ``meteo_socle.sources.openmeteo.OpenMeteoForecast``), calcule les
indicateurs envoyés dans l'email matinal :

- Température min / max sur 24 h et 48 h (fenêtre ancrée à minuit local)
- Cumuls de pluie 24 / 48 h
- Vent moyen et rafales maximaux 24 h (km/h)
- ETP cumulée 24 h (caractère séchant du jour) + série horaire 48 h
  utilisée par l'email pour reconstruire ETP du jour et bilan eau 48 h
- Périodes de Smith mildiou tomate sur 48 h

**Cohérence inter-apps (cf. principe #4 rigueur scientifique)** :
l'ETP est calculée par ``meteo_socle.indices.etp_fao.calcul_etp``
(FAO Penman-Monteith horaire, ADR-0004), **pas** reprise du champ
``etp_open_meteo`` du fournisseur. Cela garantit la même méthode dans
toutes les apps (Veille, Opérationnelle, Climato) et nous donne la
maîtrise des hypothèses (R_so via pvlib, clearness, G jour/nuit).
``etp_open_meteo`` reste un cross-check possible mais n'est pas utilisé
en production.

Température : min et max sur chaque fenêtre (24 h et 48 h) **sans
découpage nuit/jour** pour les risques de **gel** (min : irrigation
48 h, cultures 24 h) et de **canicule** (max : aération 48 h, stress
24 h) — ces risques se surveillent à toute heure. **Exception** : le
**risque maladies** (« nuit douce ») utilise un min restreint à la
**nuit à venir** (J+1, heures locales [0, 6)),
``temperature_min_nuit_prochaine_celsius``. Le découpage nuit/jour
visuel (Nuit / Matin / Après-midi / Soir) vit dans la grille du mail.
La fenêtre démarre à **minuit local** (et non à l'heure d'envoi).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from meteo_socle.indices.etp_fao import calcul_etp
from meteo_socle.indices.mildiou import agreger_critere_journalier, smith_periods
from meteo_socle.sources.openmeteo_runs import ancre_creneau, creneau_run

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
    temperature_min_48h_celsius: float
    temperature_max_48h_celsius: float

    cumul_pluie_24h_mm: float
    cumul_pluie_48h_mm: float

    vent_max_24h_kmh: float
    rafales_max_24h_kmh: float
    direction_vent_dominante_deg: float
    direction_vent_dominante_cardinal: str

    etp_jour_mm: float

    prob_pluie_max_24h_pct: float
    prob_pluie_max_48h_pct: float

    # Min de température sur la nuit À VENIR (J+1, heures locales [0, 6)),
    # pour l'alerte risque_maladies (« nuit douce »). Distinct des min
    # 24/48 h qui portent sur toute la fenêtre (risques de gel, à toute
    # heure). NaN si la prévision ne couvre pas cette nuit.
    temperature_min_nuit_prochaine_celsius: float = float("nan")

    # Série ETP horaire 48 h (mm/h) calculée par le socle. Permet à
    # email.py de reconstruire ETP du jour J+0 / J+1 et le bilan eau
    # 48 h sans dupliquer la logique. Indexée comme la prévision.
    etp_horaire_48h: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    # Mildiou Smith periods (cf. ADR-0007). Liste de dates locales sur
    # les 48 h à venir où une période de Smith est détectée.
    # Vide = pas de période ; len ≥ 1 = au moins une période sur la
    # fenêtre. Détail journalier (T_min, h HR ≥ seuil) inclus pour
    # transparence dans le mail.
    mildiou_smith_jours_a_risque: list[pd.Timestamp] = field(default_factory=list)
    mildiou_smith_detail: pd.DataFrame | None = None

    # Métadonnées prévision : 1er pas horaire effectivement utilisé après
    # filtrage ``now_utc`` (proxy "T+0" pour le mail).
    prevision_t0_utc: pd.Timestamp | None = None


def ancre_fenetre(now_utc: pd.Timestamp, tz: str = "UTC") -> pd.Timestamp:
    """Borne basse de la fenêtre 48 h = init du run-cœur (AROME) du créneau.

    Depuis ADR-0011 (D5), on raisonne **tout en UTC** et on ancre la fenêtre
    sur l'**init du run** (00Z le matin, 12Z l'après-midi), et non plus sur la
    demi-journée locale : le début de fenêtre coïncide ainsi exactement avec le
    début du run (zéro trou) et avec les bins de période UTC
    (0-6/6-12/12-18/18-24). Le paramètre ``tz`` est conservé pour compatibilité
    d'appel mais **ignoré** (ancrage UTC). Retourne un Timestamp tz-aware UTC.
    """
    return ancre_creneau(now_utc)


def moment_envoi(now_utc: pd.Timestamp, tz: str = "UTC") -> str:
    """Libellé du moment d'envoi : ``"matin"`` ou ``"après-midi"``.

    Déduit du **créneau de run UTC** (bornes 05:30 / 17:30 UTC, cf.
    ``meteo_socle.sources.openmeteo_runs.creneau_run``), pour rester cohérent
    avec les runs réellement servis (ADR-0011 D3). Le paramètre ``tz`` est
    conservé pour compatibilité mais **ignoré**.
    """
    creneau, _ = creneau_run(now_utc)
    return "matin" if creneau == "matin" else "après-midi"


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
        ``vitesse_vent_10m`` et ``rafales_vent_10m`` m/s).
    now_utc :
        Référence temporelle. La fenêtre démarre à **minuit local** du
        jour de ``now_utc`` (les heures antérieures sont ignorées) ;
        ``config["site"]["tz"]`` donne le fuseau.
    config :
        Configuration Veille (cf. ``apps.veille.config.load_config``).

    Returns
    -------
    IndicateursVeille
        Dataclass groupant les valeurs synthétiques.

    Raises
    ------
    ValueError
        Si la prévision ne contient aucune heure ≥ ``now_utc``.
    """
    # Fenêtre ancrée sur la dernière demi-journée locale (00 h le matin,
    # 12 h l'après-midi — cf. ``ancre_fenetre``) plutôt que sur ``now_utc``
    # lui-même, pour coïncider avec la grille du mail et inclure les heures
    # déjà écoulées de la demi-journée (observées via ``past_days=1`` au
    # fetch). h24 = [ancre ; ancre+24h], h48 = [ancre ; ancre+48h].
    # ADR-0011 D5 : tout en UTC, indicateurs agronomiques inclus. Les bins
    # (fenêtre 48 h, nuit-douce, mildiou Smith) sont définis sur l'heure UTC,
    # alignés sur les cycles de run — plus aucun raisonnement en heure locale.
    tz = "UTC"
    debut = ancre_fenetre(now_utc, tz)
    df = prevision.loc[prevision.index >= debut].copy()
    if df.empty:
        raise ValueError(
            "La prévision ne contient aucune heure ≥ ancre de demi-journée — "
            "vérifier la fraîcheur du fetch Open-Meteo."
        )
    df = df.sort_index()

    h24 = df.head(24)
    h48 = df.head(48)

    temperature_celsius_24h = h24["temperature_2m"] - KELVIN_OFFSET
    temperature_celsius_48h = h48["temperature_2m"] - KELVIN_OFFSET

    # Min de la nuit À VENIR (J+1, heures locales [0, 6)) — pour le
    # risque maladies (« nuit douce »). Le mail part le matin : la nuit
    # actionnable est celle de la nuit prochaine (demain 00-06 h), pas
    # celle déjà écoulée. NaN si non couverte.
    jour_j1 = now_utc.tz_convert(tz).normalize() + pd.Timedelta(days=1)
    idx_local = df.index.tz_convert(tz)
    masque_nuit = (idx_local.normalize() == jour_j1) & (idx_local.hour >= 0) & (idx_local.hour < 6)
    t_nuit_celsius = df.loc[masque_nuit, "temperature_2m"] - KELVIN_OFFSET
    t_min_nuit_prochaine = float(t_nuit_celsius.min()) if not t_nuit_celsius.empty else float("nan")

    # ETP via le socle FAO Penman-Monteith (cohérence inter-apps).
    site = config["site"]
    etp_horaire_24h = calcul_etp(
        h24[_INPUTS_ETP], site["latitude"], site["longitude"], site["altitude"]
    )
    etp_horaire_48h = calcul_etp(
        h48[_INPUTS_ETP], site["latitude"], site["longitude"], site["altitude"]
    )
    etp_24h = float(etp_horaire_24h.sum())
    pluie_24h = float(h24["precipitation"].sum())

    # Probabilité de pluie : colonne optionnelle (selon les variables
    # demandées dans le fetch). On donne 0 si absente.
    def _prob_max(window: pd.DataFrame) -> float:
        if "probabilite_pluie_pct" not in window.columns:
            return 0.0
        return float(window["probabilite_pluie_pct"].max())

    # Direction dominante sur 24h, pondérée par la vitesse.
    dir_deg = direction_dominante_vecteur(h24)
    dir_card = degrees_to_cardinal(dir_deg) if not np.isnan(dir_deg) else ""

    # Smith periods sur 48 h. Implémentation socle = ADR-0007.
    mildiou_cfg = config["indicateurs"].get("mildiou_smith", {"actif": False})
    smith_jours: list[pd.Timestamp] = []
    smith_detail: pd.DataFrame | None = None
    if mildiou_cfg.get("actif", False):
        tz_loc = "UTC"  # ADR-0011 D5 : agrégation Smith par jour UTC
        # On agrège l'horizon 48 h. Ajoute la veille du premier jour
        # affiché (h≥now) si dispo dans la prévision, sinon le premier
        # jour ne pourra pas qualifier (par construction Smith demande
        # un jour A observable).
        h48_etendu = prevision.head(48 + 24).sort_index()
        critere = agreger_critere_journalier(
            h48_etendu,
            tz_locale=tz_loc,
            hr_seuil=float(mildiou_cfg.get("hr_seuil", 0.90)),
        )
        smith = smith_periods(
            critere,
            t_min_celsius=float(mildiou_cfg.get("t_min_celsius", 10.0)),
            heures_min=int(mildiou_cfg.get("heures_min", 11)),
        )
        # Bornes du jour local de "demain" inclus jusqu'à J+2.
        now_loc = now_utc.tz_convert(tz_loc)
        debut = (now_loc.normalize() + pd.Timedelta(days=1)).tz_localize(None)
        fin = (now_loc.normalize() + pd.Timedelta(days=2)).tz_localize(None)
        fenetre = critere.loc[debut:fin]
        smith_detail = fenetre.copy()
        smith_detail["smith_period"] = smith.reindex(fenetre.index, fill_value=False)
        smith_jours = list(smith_detail.index[smith_detail["smith_period"]])

    return IndicateursVeille(
        temperature_min_24h_celsius=float(temperature_celsius_24h.min()),
        temperature_max_24h_celsius=float(temperature_celsius_24h.max()),
        temperature_min_48h_celsius=float(temperature_celsius_48h.min()),
        temperature_max_48h_celsius=float(temperature_celsius_48h.max()),
        temperature_min_nuit_prochaine_celsius=t_min_nuit_prochaine,
        cumul_pluie_24h_mm=pluie_24h,
        cumul_pluie_48h_mm=float(h48["precipitation"].sum()),
        vent_max_24h_kmh=float(h24["vitesse_vent_10m"].max() * MS_TO_KMH),
        rafales_max_24h_kmh=float(h24["rafales_vent_10m"].max() * MS_TO_KMH),
        direction_vent_dominante_deg=dir_deg if not np.isnan(dir_deg) else 0.0,
        direction_vent_dominante_cardinal=dir_card,
        etp_jour_mm=etp_24h,
        prob_pluie_max_24h_pct=_prob_max(h24),
        prob_pluie_max_48h_pct=_prob_max(h48),
        etp_horaire_48h=etp_horaire_48h,
        mildiou_smith_jours_a_risque=smith_jours,
        mildiou_smith_detail=smith_detail,
        prevision_t0_utc=df.index[0],
    )
