"""Bilan hydrique culture-spécifique et besoin d'irrigation.

Calcule jour par jour, pour une culture donnée à un stade donné sur un
sol donné :

- la Réserve Utile (RU) en eau du sol : eau disponible entre capacité
  au champ et point de flétrissement permanent, dépendant de la
  texture du sol et de la profondeur d'enracinement (corrigée du
  fraction cailloux) ;
- la Réserve Facilement Utilisable (RFU) : fraction de RU réellement
  mobilisable sans stress hydrique (typiquement 50-70 % selon la
  culture) ;
- l'évapotranspiration maximale de la culture ETM = Kc · ET₀
  (Allen et al. 1998 FAO 56 Eq. 56), avec coefficients culturaux Kc
  par culture × stade phénologique fournis par ARDEPI ;
- le besoin en irrigation : déficit entre RFU cible et bilan
  (RFU + déficit_RFU + précipitations − ETM).

Paramètres de sol et profondeurs d'enracinement issus des fiches
techniques maraîchage.

Références
----------

- Allen, R.G., Pereira, L.S., Raes, D., Smith, M., 1998.
  *Crop Evapotranspiration*. FAO Bulletin 56, Rome. ETM via Kc :
  chapitre 6.
- ARDEPI, *Estimer ses besoins en eau — Maraîchage*. Coefficients Kc
  par culture × stade.
  <https://www.ardepi.fr/nos-services/vous-etes-irrigant/estimer-ses-besoins-en-eau/maraichage/>
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# Coefficients culturaux (Kc) par culture et par stade — fichier ARDEPI
# packagé avec le module (cf. ADR-0003 Phase B note sur l'adaptation
# verbatim → packaged du path).
FILEPATH_KC: Path = Path(__file__).parent / "coefficients_culturaux_ardepi.json"

# Lecture des coefficients culturaux à l'import.
with open(FILEPATH_KC) as f:
    KC: dict[str, dict[str, float]] = json.load(f)

# Réserve Utile par cm de terre fine (mm eau / cm sol fin), fonction de
# la texture du sol. Valeurs issues des références agronomiques
# standards (fiches RECYCLAGE / ARDEPI). Les terres limoneuses ont la
# meilleure rétention, les sableuses la plus faible.
RU_PAR_CM_DE_TF: dict[str, float] = {
    "Terres argileuses": 1.85,
    "Argiles sableuses": 1.7,
    "Argiles sablo-limoneuses": 1.8,
    "Argiles limono-sableuses": 1.8,
    "Argiles limoneuses": 1.9,
    "Terres argilo-sableuses": 1.7,
    "Terres argilo-limono-sableuses": 1.8,
    "Terres argilo-limoneuses": 2.0,
    "Terres sablo-argileuses": 1.4,
    "Terres sablo-limono-argileuses": 1.5,
    "Terres limono-sablo-argileuses": 1.65,
    "Terres limono-argileuses": 2.00,
    "Terres sableuses": 0.7,
    "Terres sablo-limoneuses": 1.0,
    "Terres limono-sableuses": 1.55,
    "Terres limoneuses": 1.8,
}

# Profondeur d'enracinement typique par culture maraîchère (cm). Issue
# des fiches techniques ARDEPI. Les cultures à racines profondes
# (cucurbitacées, solanacées) atteignent ~30 cm ; les cultures à
# racines superficielles (radis, salades) ~15 cm.
PROFONDEUR_ENRACINEMENT_TYPIQUE: dict[str, float] = {
    "Ail": 20.0,
    "Artichaut": 20.0,
    "Asperge": 20.0,
    "Aubergine": 30.0,
    "Betterave": 20.0,
    "Carotte": 30.0,
    "Chou fleur": 20.0,
    "Choux": 20.0,
    "Courge": 30.0,
    "Courgette": 30.0,
    "Epinard": 20.0,
    "Fraisier": 30.0,
    "Haricot": 20.0,
    "Melon": 30.0,
    "Oignon": 20.0,
    "Poireau": 30.0,
    "Pois": 20.0,
    "Poivron": 30.0,
    "Pomme de terre": 30.0,
    "Radis": 15.0,
    "Salade": 15.0,
    "Soja": 20.0,
    "Tomate de conserve": 30.0,
    "Tomate": 30.0,
}

# Variables météorologiques utilisées pour le bilan hydrique et leur
# méthode d'agrégation journalière (info utilitaire pour les modules
# d'agrégation aval).
VARIABLES_CALCUL_BILAN: dict[str, str] = {
    "etp": "sum",
    "precipitation": "sum",
}


def calcul_reserve_utile(
    texture: str,
    fraction_cailloux: float,
    culture: str,
    fraction_ru_remplie: float,
) -> tuple[float, float, float, float]:
    """Calcule la Réserve Utile en eau du sol pour une culture donnée.

    Parameters
    ----------
    texture :
        Nom de texture sol parmi les clés de ``RU_PAR_CM_DE_TF``.
    fraction_cailloux :
        Fraction volumique de cailloux dans la couche racinaire
        (0-1) — réduit la profondeur effective de terre fine.
    culture :
        Nom de culture parmi les clés de
        ``PROFONDEUR_ENRACINEMENT_TYPIQUE``.
    fraction_ru_remplie :
        État de remplissage initial de la RU (0-1) — 1.0 = capacité au
        champ, 0.0 = point de flétrissement.

    Returns
    -------
    profondeur_enracinement :
        Profondeur d'enracinement nominale (cm).
    profondeur_terrefine :
        Profondeur effective de terre fine = enracinement × (1 − cailloux).
    ru :
        Réserve Utile totale (mm).
    ru_remplie :
        Stock d'eau actuel (mm) = ru × fraction_ru_remplie.
    """
    ru_par_cm_de_tf_texture = RU_PAR_CM_DE_TF[texture]
    profondeur_enracinement = PROFONDEUR_ENRACINEMENT_TYPIQUE[culture]
    profondeur_terrefine = profondeur_enracinement * (1.0 - fraction_cailloux)
    ru = ru_par_cm_de_tf_texture * profondeur_terrefine
    ru_remplie = ru * fraction_ru_remplie
    return profondeur_enracinement, profondeur_terrefine, ru, ru_remplie


def calcul_reserve_facilement_utilisable(
    ru_remplie: float | pd.Series, ru_vers_rfu: float
) -> float | pd.Series:
    """Calcule la Réserve Facilement Utilisable (RFU) en mm.

    La RFU est la fraction de la RU mobilisable par la culture sans
    stress (typiquement 50-70 %). Au-delà, la plante régule sa
    transpiration et l'ETM devient inférieure à Kc · ET₀.
    """
    return ru_remplie * ru_vers_rfu


def calcul_etm_culture(
    culture: str, stade: str, df_meteo: pd.DataFrame
) -> pd.Series:
    """Évapotranspiration maximale culturale ETM = Kc · ET₀ (FAO 56 Eq. 56).

    Parameters
    ----------
    culture :
        Nom de culture parmi les clés de ``KC``.
    stade :
        Stade phénologique parmi les clés de ``KC[culture]``.
    df_meteo :
        DataFrame avec colonne ``etp`` (ET₀ FAO en mm).

    Returns
    -------
    pd.Series
        ETM en mm, indexée comme ``df_meteo``.
    """
    kc_culture = KC[culture][stade]
    return kc_culture * df_meteo["etp"]


def calcul_bilan(
    df_meteo: pd.DataFrame | pd.Series,
    texture: str,
    fraction_cailloux: float,
    culture: str,
    stade: str,
    fraction_ru_remplie: float,
    ru_vers_rfu: float,
    seuil_irrigation: float,
    hauteur_vers_duree_irrigation: float,
    rfu_cible: float | pd.Series | None = None,
) -> pd.DataFrame | pd.Series:
    """Bilan hydrique culture-spécifique et besoin d'irrigation.

    Pour chaque pas de temps de ``df_meteo`` (typiquement journalier),
    calcule l'ensemble : RU, RFU, déficit, ETM, besoin d'irrigation,
    déclenchement et durée d'arrosage.

    Le bilan est traité **sans report inter-pas** — chaque ligne est
    calculée indépendamment avec un état initial RU = fraction_ru_remplie.
    Pour un suivi temporel avec carry-over, appliquer ce calcul
    récursivement en mettant à jour ``fraction_ru_remplie`` après
    chaque jour.

    Parameters
    ----------
    df_meteo :
        DataFrame ou Series avec colonnes ``etp`` et ``precipitation``
        (mm).
    texture, fraction_cailloux :
        Caractéristiques du sol (cf. ``calcul_reserve_utile``).
    culture, stade :
        Culture × stade phénologique pour Kc.
    fraction_ru_remplie, ru_vers_rfu :
        État RU initial (0-1) et fraction RFU/RU.
    seuil_irrigation :
        Seuil de besoin d'irrigation au-dessus duquel le déclenchement
        est recommandé (mm).
    hauteur_vers_duree_irrigation :
        Coefficient conversion hauteur de pluie d'arrosage → durée
        (h mm⁻¹).
    rfu_cible :
        RFU cible après irrigation. Si ``None``, utilise la RFU
        calculée.

    Returns
    -------
    pd.DataFrame | pd.Series
        Bilan détaillé avec colonnes : etp, profondeur_enracinement,
        profondeur_terrefine, ru, rfu, rfu_deficit, precipitation,
        etm_culture, besoin_irrigation, rfu_cible, irrigation,
        duree_irrigation.
    """
    if isinstance(df_meteo, pd.Series):
        df: pd.DataFrame | pd.Series = pd.Series(dtype=float)
    else:
        df = pd.DataFrame(index=df_meteo.index, dtype=float)

    # Convention : ETP et ETM sont compteurs négatifs (sortie d'eau) ;
    # précipitations positives.
    df["etp"] = -df_meteo["etp"]

    cru = calcul_reserve_utile(
        texture, fraction_cailloux, culture, fraction_ru_remplie
    )
    df["profondeur_enracinement"] = cru[0]
    df["profondeur_terrefine"] = cru[1]
    df["ru"] = cru[2]
    ru_remplie = cru[3]
    df["rfu"] = calcul_reserve_facilement_utilisable(df["ru"], ru_vers_rfu)
    df["rfu_deficit"] = (
        calcul_reserve_facilement_utilisable(ru_remplie, ru_vers_rfu) - df["rfu"]
    )

    df["precipitation"] = df_meteo["precipitation"]
    df["etm_culture"] = -calcul_etm_culture(culture, stade, df_meteo)

    if rfu_cible is None:
        rfu_cible = df["rfu"]

    df["besoin_irrigation"] = rfu_cible - (
        df["rfu"] + df["rfu_deficit"] + df["precipitation"] + df["etm_culture"]
    )
    df["rfu_cible"] = rfu_cible
    df["irrigation"] = df["besoin_irrigation"] > seuil_irrigation
    df["duree_irrigation"] = hauteur_vers_duree_irrigation * np.where(
        df["irrigation"], df["besoin_irrigation"], 0
    )
    return df
