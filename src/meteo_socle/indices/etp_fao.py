import numpy as np
import pandas as pd
from pvlib import irradiance, location
import pytz

# Variables météorologiques utilisées pour le calcul de l'ETP
# et leur méthode d'aggrégation journalière
VARIABLES_CALCUL_ETP = {
    'vitesse_vent_10m': 'mean',
    'temperature_2m': 'mean',
    'humidite_relative': 'mean',
    'rayonnement_global': 'sum'
}

# Chaleur latente de vaporisation de l’eau (MJ kg-1)
LAMBDA = 2.45

# Facteur de la constante psychrométrique (kPa K-1)
FACTEUR_GAMMA = 0.665e-3

# Constante de Stefan-Boltzmann (MJ m-2 K-4 h-1)
SIGMA = 2.043e-10 

# Albedo
ALPHA = 0.23

# Émissivité
EPSILON = 1.0

def calcul_rayonnement_net_ondes_courtes(df):
    # Rayonnement solaire incident en MJ m-2 h-1
    r_s = df['rayonnement_global'] * 1.e-6

    # Calcul du rayonnement net aux ondes courtes
    r_ns = (1 - ALPHA) * r_s

    return r_ns

def calcul_rayonnement_net_ondes_longues(df, ee, site):
    # Rayonnement solaire incident en MJ m-2 h-1
    r_s = df['rayonnement_global'] * 1.e-6

    # Localisation du temps
    time = pd.DatetimeIndex(df.index)
    local_time = time.tz_convert(site.tz)

    # Calcul du rayonnement extraterrestre normal
    r_a_dni = irradiance.get_extra_radiation(local_time) * 3600 * 1.e-6

    # Calcul du zenith solaire
    zenith = site.get_solarposition(times=local_time)['zenith']

    # Calcul du rayonnement extraterrestre horizontal
    r_a = np.maximum(0., r_a_dni * np.cos(np.deg2rad(zenith)))

    # Calcul du rayonnement solaire incident pour un ciel clair
    r_so = (0.75 + 2.e-5 * site.altitude) * r_a

    # Conversion du temps vers UTC
    r_so.index = r_so.index.tz_convert('UTC')

    # Calcul de la clareté
    clarete = np.minimum(1., r_s / r_so)

    # Durant la nuit la clareté est suppossée égale à celle 2h avant le couché
    # Si des heures de journée avant la nuit ne sont pas disponibles on utilise
    # les heures après le levé
    is_day = zenith.values < 90.
    is_day_short = np.roll(is_day, 1) & np.roll(is_day, -1)
    clarete = clarete.where(is_day_short).ffill(
        axis='index').bfill(axis='index')

    # Calcul du rayonnement net aux ondes longues
    r_nl = SIGMA * df['temperature_2m']**4 * (0.34 - 0.14 * np.sqrt(ee)) * (
        1.35 * clarete - 0.35)

    return r_nl, zenith

def calcul_etp(df, latitude, longitude, altitude):
    '''Calcul de l'évapotranspiration potentielle pour une station.'''
    tz = pytz.country_timezones('FR')[0]
    site = location.Location(
        latitude, longitude, altitude=altitude, tz=tz)
    
    # Calcul de la pression de vapeur saturante (kPa)
    es = 0.6108 * np.exp(17.27 * (
        df['temperature_2m'] - 273.15) / (df['temperature_2m'] - 35.85))
    
    # Calcul de la pente de la courbe de pression de vapeur à la température moyenne de l'air (kPa K-1)
    delta = 4098. * es / (df['temperature_2m'] - 35.85)**2

    # Calcul standard de la pression moyenne en fonction de l'altitude (kPa)
    pression = 101.3 * ((293. - 0.0065 * site.altitude) / 293.)**5.26

    # Calcul de la constante psychrométrique
    gamma = FACTEUR_GAMMA * pression

    # Calcul de la pression de vapeur effective (kPa)
    ee = es * df['humidite_relative']

    # Calcul du rayonnement net
    r_ns = calcul_rayonnement_net_ondes_courtes(df)
    r_nl, zenith = calcul_rayonnement_net_ondes_longues(df, ee, site)
    r_n = r_ns - r_nl

    # Calcul du flux du sol
    g_sol = (0.1 * r_n).where(zenith < 90., 0.5 * r_n)
   
    # Calcul de la vitesse du vent à 2 m à partir de celle à 10 m
    u2 = df['vitesse_vent_10m'] * 4.87 / np.log(67.8 * 10 - 5.42)

    # Calcul de l'ETP (mm h-1)
    denominateur = delta + gamma * (1. + 0.34 * u2)
    etp1 = np.maximum(0, delta * (r_n - g_sol) / LAMBDA / denominateur)
    etp2 = np.maximum(0, gamma * 37. / df['temperature_2m'] * u2 * (
        es - ee) / denominateur)
    etp = etp1 + etp2

    return etp