import json
import numpy as np
import pandas as pd
from pathlib import Path


# Coefficients culturaux (KC) par culture et par stade
# Adaptation minimale verbatim → packaged : path relative au module pour
# permettre l'import depuis n'importe quel cwd (cf. ADR-0003 Phase B).
FILEPATH_KC = Path(__file__).parent / "coefficients_culturaux_ardepi.json"

# Lecture des coefficients culturaux
with open(FILEPATH_KC) as f:
    KC = json.load(f)

# Réserve Utile (RU) par cm de terre fine (mm/cm de terre fine) en fonction de la texture du sol
RU_PAR_CM_DE_TF = {
    'Terres argileuses': 1.85,
    'Argiles sableuses': 1.7, 'Argiles sablo-limoneuses': 1.8, 'Argiles limono-sableuses': 1.8, 'Argiles limoneuses': 1.9,
    'Terres argilo-sableuses': 1.7, 'Terres argilo-limono-sableuses': 1.8, 'Terres argilo-limoneuses': 2.,
    'Terres sablo-argileuses': 1.4, 'Terres sablo-limono-argileuses': 1.5, 'Terres limono-sablo-argileuses': 1.65, 'Terres limono-argileuses': 2.00,
    'Terres sableuses': 0.7, 'Terres sablo-limoneuses': 1., 'Terres limono-sableuses': 1.55, 'Terres limoneuses': 1.8
}

# Profondeurs d'enracinement typiques
PROFONDEUR_ENRACINEMENT_TYPIQUE = {
    "Ail": 20.,
    "Artichaut": 20.,
    "Asperge": 20.,
    "Aubergine": 30.,
    "Betterave": 20.,
    "Carotte": 30.,
    "Chou fleur": 20.,
    "Choux": 20.,
    "Courge": 30.,
    "Courgette": 30.,
    "Epinard": 20.,
    "Fraisier": 30.,
    "Haricot": 20.,
    "Melon": 30.,
    "Oignon": 20.,
    "Poireau": 30.,
    "Pois": 20.,
    "Poivron": 30.,
    "Pomme de terre": 30.,
    "Radis": 15.,
    "Salade": 15.,
    "Soja": 20.,
    "Tomate de conserve": 30.,
    "Tomate": 30.
}

# Variables météorologiques utilisées pour le bilan hydrique
# et leur méthode d'aggrégation journalière
VARIABLES_CALCUL_BILAN = {
    'etp': 'sum',
    'precipitation': 'sum'
}

def calcul_reserve_utile(
    texture, fraction_cailloux, culture, fraction_ru_remplie):
    ''' Calcul de la RU (mm).'''
    # RU par cm de terre fine pour cette texture
    ru_par_cm_de_tf_texture = RU_PAR_CM_DE_TF[texture]

    # Calcul de la profondeur de terre fine
    profondeur_enracinement = PROFONDEUR_ENRACINEMENT_TYPIQUE[culture]
    profondeur_terrefine = profondeur_enracinement * (1. - fraction_cailloux)

    ru = ru_par_cm_de_tf_texture * profondeur_terrefine
    
    ru_remplie = ru * fraction_ru_remplie

    return profondeur_enracinement, profondeur_terrefine, ru, ru_remplie

def calcul_reserve_facilement_utilisable(ru_remplie, ru_vers_rfu):
    ''' Calcul de la RFU (mm).'''
    return ru_remplie * ru_vers_rfu

def calcul_etm_culture(culture, stade, df_meteo):
    ''' Calcul de l'évalotranspiration maximale de la culture (mm).'''
    # KC de la culture pour ce stade
    kc_culture = KC[culture][stade]

    etm_culture = kc_culture * df_meteo['etp']

    return etm_culture

def calcul_bilan(
    df_meteo,
    texture, fraction_cailloux,
    culture, stade,
    fraction_ru_remplie, ru_vers_rfu,
    seuil_irrigation, hauteur_vers_duree_irrigation,
    rfu_cible=None
):
    ''' Calcul du besoin en irrigation (mm).'''
    if isinstance(df_meteo, pd.Series):
        df = pd.Series(dtype=float)
    else:
        df = pd.DataFrame(index=df_meteo.index, dtype=float)

    df['etp'] = -df_meteo['etp']

    cru = calcul_reserve_utile(texture, fraction_cailloux, culture,
                               fraction_ru_remplie)
    df['profondeur_enracinement'] = cru[0]
    df['profondeur_terrefine'] = cru[1]
    df['ru'] = cru[2]
    ru_remplie = cru[3]
    df['rfu'] = calcul_reserve_facilement_utilisable(
            df['ru'], ru_vers_rfu)
    df['rfu_deficit'] = calcul_reserve_facilement_utilisable(
        ru_remplie, ru_vers_rfu) - df['rfu']
    
    df['precipitation'] = df_meteo['precipitation']
    
    df['etm_culture'] = -calcul_etm_culture(culture, stade, df_meteo)

    if rfu_cible is None:
        rfu_cible = df['rfu']

    df['besoin_irrigation'] = rfu_cible - (
        df['rfu'] + df['rfu_deficit'] + df['precipitation'] + df['etm_culture'])
    
    df['rfu_cible'] = rfu_cible

    df['irrigation'] = df['besoin_irrigation'] > seuil_irrigation

    df['duree_irrigation'] = hauteur_vers_duree_irrigation * np.where(
        df['irrigation'], df['besoin_irrigation'], 0)

    return df