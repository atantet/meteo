"""Seuils de référence Météo-France — source unique de vérité.

Définitions officielles des indices de température MF (cf. glossaire de
l'état de l'art climat). Centralisées ici pour que les apps citent toutes
les *mêmes* valeurs (principe de cohérence inter-apps) : App 2 les utilise
pour des **libellés de contexte** (descriptifs, jamais des alertes — la
Vigilance MF reste seule sur chaleur/froid), le Climato pourra les
réutiliser pour le comptage de jours caractéristiques.

Sémantique des bornes (à respecter exactement, cf. glossaire) :

- **Jour de gel** : T° min **≤ 0 °C** (borne incluse).
- **Journée chaude** : T° max **> 25 °C** ; **forte chaleur** **> 30 °C** ;
  **très forte chaleur** **> 35 °C** (bornes strictes).
- **Nuit tropicale** : T° min **≥ 20 °C** (borne incluse).

NB : ce module ne porte **aucune** notion de vague de chaleur / canicule —
c'est un indicateur thermique national (moyenne 30 stations), non calculable
ponctuellement, et du ressort exclusif de la Vigilance MF.
"""

from __future__ import annotations

import math

# Seuils officiels MF, en °C (unités d'affichage : ces indices sont définis
# en °C par Météo-France).
GEL_TMIN_CELSIUS_MAX: float = 0.0
NUIT_TROPICALE_TMIN_CELSIUS_MIN: float = 20.0
JOURNEE_CHAUDE_TMAX_CELSIUS_MIN: float = 25.0
FORTE_CHALEUR_TMAX_CELSIUS_MIN: float = 30.0
TRES_FORTE_CHALEUR_TMAX_CELSIUS_MIN: float = 35.0

# Libellés affichés (vocabulaire MF officiel).
LABEL_GEL: str = "gel"
LABEL_NUIT_TROPICALE: str = "nuit tropicale"
LABEL_JOURNEE_CHAUDE: str = "journée chaude"
LABEL_FORTE_CHALEUR: str = "forte chaleur"
LABEL_TRES_FORTE_CHALEUR: str = "très forte chaleur"


def etiquettes_temperature(
    t_min_celsius: float | None,
    t_max_celsius: float | None,
) -> list[str]:
    """Libellés MF de contexte pour une journée, à partir de T° min/max (°C).

    Renvoie au plus deux libellés : un côté « min » (gel **ou** nuit
    tropicale, mutuellement exclusifs) et un côté « max » (le palier de
    chaleur **le plus haut** atteint, sans empiler les paliers inférieurs).
    Liste vide si aucune borne n'est franchie ou si les valeurs sont
    indisponibles (None / NaN).

    Descriptif uniquement : nomme ce qu'est la valeur, n'invite à rien.
    """
    labels: list[str] = []

    # `is not None` est inliné (et non délégué à un helper) pour que le type
    # checker propage le narrowing float|None → float aux comparaisons.
    if t_min_celsius is not None and not math.isnan(t_min_celsius):
        if t_min_celsius <= GEL_TMIN_CELSIUS_MAX:
            labels.append(LABEL_GEL)
        elif t_min_celsius >= NUIT_TROPICALE_TMIN_CELSIUS_MIN:
            labels.append(LABEL_NUIT_TROPICALE)

    if t_max_celsius is not None and not math.isnan(t_max_celsius):
        if t_max_celsius > TRES_FORTE_CHALEUR_TMAX_CELSIUS_MIN:
            labels.append(LABEL_TRES_FORTE_CHALEUR)
        elif t_max_celsius > FORTE_CHALEUR_TMAX_CELSIUS_MIN:
            labels.append(LABEL_FORTE_CHALEUR)
        elif t_max_celsius > JOURNEE_CHAUDE_TMAX_CELSIUS_MIN:
            labels.append(LABEL_JOURNEE_CHAUDE)

    return labels
