from io import StringIO
import json
import numpy as np
import pandas as pd
from pathlib import Path
import requests
import time
import warnings

# Host
HOST = 'https://public-api.meteofrance.fr'
DOMAIN = 'public'
VERSION = 'v1'
SECTION_LISTE_STATIONS = 'liste-stations'
AVAILABLE_APIS = ['DPObs', 'DPPaquetObs', 'DPClim']
FMT = 'csv'

# Definitions pour accéder à l'API Météo-France via un token OAuth2
# unique application id : you can find this in the curl's command to generate jwt token 
# url to obtain acces token
TOKEN_URL = "https://portail-api.meteofrance.fr/token"

# Étiquettes de la latitude et de la longitude
LATLON_LABELS = {
    'DPObs': ['Latitude', 'Longitude'],
    'DPPaquetObs': ['Latitude', 'Longitude'],
    'DPClim': ['lat', 'lon']
}

# Étiquette des noms des stations
STATION_NAME_LABEL = {
    'DPObs': 'Nom_usuel',
    'DPPaquetObs': 'Nom_usuel',
    'DPClim': 'nom'
}

# Étiquette des identifiants des stations
ID_STATION_LABEL = {
    'DPObs': 'Id_station',
    'DPPaquetObs': 'Id_station',
    'DPClim': 'id'
}

# Étiquette des identifiants des stations dans les donnees
ID_STATION_DONNEE_LABEL = {
    'DPObs': 'geo_id_insee',
    'DPPaquetObs': 'geo_id_insee',
    'DPClim': 'POSTE'
}

# Étiquette du drapeau d'ouverture des stations
OUVERT_STATION_LABEL = {
    'DPObs': None,
    'DPPaquetObs': None,
    'DPClim': 'posteOuvert'
}

# Étiquette du drapeau du caractère public des stations
PUBLIC_STATION_LABEL = {
    'DPObs': None,
    'DPPaquetObs': None,
    'DPClim': 'postePublic'
}

# Étiquette du type de station
TYPE_STATION_LABEL = {
    'DPObs': None,
    'DPPaquetObs': None,
    'DPClim': 'typePoste'
}

# Étiquette de l'indice temporel
TIME_LABEL = {
    'DPObs': 'validity_time',
    'DPPaquetObs': 'validity_time',
    'DPClim': 'DATE'
}

# Conversion de unités des variables
identite = lambda x: x
VARIABLES_CONVERSION_UNITES = {
    'DPObs': {
        'rayonnement_global': identite,
        'temperature_2m': identite,
        'humidite_relative': lambda x: x / 100,
        'vitesse_vent_10m': identite,
        'precipitation': identite,
        'etp': identite
    },
    'DPClim': {
        'rayonnement_global': lambda x: x * 1.e4,
        'temperature_2m': lambda x: x + 273.15,
        'humidite_relative': lambda x: x / 100,
        'vitesse_vent_10m': identite,
        'precipitation': identite,
        'etp': identite
    }
}
VARIABLES_CONVERSION_UNITES['DPPaquetObs'] = VARIABLES_CONVERSION_UNITES['DPObs']

# Étiquettes des variables
VARIABLES_LABELS = {
    'DPObs': {
        'horaire': {
            'rayonnement_global': 'ray_glo01',
            'temperature_2m': 't',
            'humidite_relative': 'u',
            'vitesse_vent_10m': 'ff',
            'precipitation': 'rr1'
        }
    },
    'DPClim': {
        'horaire': {
            'rayonnement_global': 'GLO',
            'temperature_2m': 'T',
            'humidite_relative': 'U',
            'vitesse_vent_10m': 'FF',
            'precipitation': 'RR1',
        },
        'quotidienne': {
            'rayonnement_global': 'GLOT',
            'temperature_2m': 'TM',
            'humidite_relative': 'UM',
            'vitesse_vent_10m': 'FFM',
            'precipitation': 'RR',
            'etp': 'ETPGRILLE'
        }
    }
}
VARIABLES_LABELS['DPPaquetObs'] = VARIABLES_LABELS['DPObs']

# Unités des variables météorologiques
UNITES = {
    'rayonnement_global': 'J m-2 jour-1',
    'temperature_2m': 'K',
    'humidite_relative': '-',
    'vitesse_vent_10m': 'm s-1',
    'precipitation': 'mm jour-1',
    'etp': 'mm jour-1'
}

# Fuseau horaire
TZ = 'UTC'

# Dossier des données
DATA_DIR = Path('data')

class Client(object):
    def __init__(self, api, application_id=None):
        self.session = requests.Session()
        self._application_id = application_id
        if api not in AVAILABLE_APIS:
            raise ValueError(f"Choix invalide: {api}. "
                             f"Les choix possibles sont: {AVAILABLE_APIS}")
        self.api = api
        self.latlon_labels = LATLON_LABELS[self.api]
        self.station_name_label = STATION_NAME_LABEL[self.api]
        self.id_station_label = ID_STATION_LABEL[self.api]
        self.ouvert_station_label = OUVERT_STATION_LABEL[self.api]
        self.public_station_label = PUBLIC_STATION_LABEL[self.api]
        self.type_station_label = TYPE_STATION_LABEL[self.api]
        self.time_label = TIME_LABEL[self.api]
        self.id_station_donnee_label = ID_STATION_DONNEE_LABEL[self.api]
        self.variables_labels = VARIABLES_LABELS[self.api]
        self.variables_conversion_unites = VARIABLES_CONVERSION_UNITES[self.api]

        self.session.headers.update({'Accept': '*/*'})

    @property
    def application_id(self):
        return self._application_id

    @application_id.setter
    def application_id(self, value):
        self._application_id = value
        
    def request(self, method, url, **kwargs):
        # First request will always need to obtain a token first
        if 'Authorization' not in self.session.headers:
            self.obtain_token()
            
        # Optimistically attempt to dispatch reqest
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            response = self.session.request(method, url, **kwargs)

        if self.token_has_expired(response):
            # We got an 'Access token expired' response => refresh token
            self.obtain_token()

            # Re-dispatch the request that previously failed
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                response = self.session.request(method, url, **kwargs)

        response.raise_for_status()

        return response

    def token_has_expired(self, response):
        status = response.status_code
        content_type = response.headers['Content-Type']
        repJson = response.text

        if status == 401 and 'application/json' in content_type:
            repJson = response.text
            
            if 'Invalid JWT token' in repJson['description']:
                return True

        return False

    def obtain_token(self):
        # Obtain new token
        data = {'grant_type': 'client_credentials'}
        headers = {'Authorization': 'Basic ' + self.application_id}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            access_token_response = requests.post(
                TOKEN_URL, data=data, verify=False, allow_redirects=False, headers=headers)
        token = access_token_response.json()['access_token']

        # Update session with fresh token
        self.session.headers.update({'Authorization': 'Bearer %s' % token})

def response_text_to_frame(client, response, **kwargs):
    try:
        
        df = pd.read_csv(StringIO(response.text), sep=';', **kwargs)
    except TypeError:
        df = pd.read_json(StringIO(response.text)).set_index(
            client.id_station_label)
    
    return df

def demande(client, section, params=None, frequence=None, verify=False):
    '''Demande de la liste des stations.'''
    url = f"{HOST}/{DOMAIN}/{client.api}/{VERSION}/{section}"

    if frequence is not None:
        url += f'/{frequence}'
    
    response = client.request(
        'GET', url, params=params, verify=verify)

    return response

def liste_id_stations_vers_liste_id_departements(df_liste_stations):
    return np.unique([_ // 1000000 for _ in df_liste_stations.index])

def get_filepath_liste_stations(client, frequence=None, id_departement=None):
    filename = f"liste_stations_{client.api}"
    if frequence is not None:
        filename += f"_{frequence}"
    if id_departement is not None:
        filename += f"_{id_departement:d}"
    filename += ".csv"
    parent = DATA_DIR / client.api
    parent.mkdir(parents=True, exist_ok=True)
    filepath = parent / filename

    return filepath

def get_filepath_liste_stations_nn(
    client, ref_station_name, df_liste_stations,
    frequence=None, id_departement=None):
    filepath = get_filepath_liste_stations(
        client, frequence=frequence, id_departement=id_departement)
    str_ref_station_name = ref_station_name.lower().replace(' ', '')
    nn_nombre = len(df_liste_stations)
    str_nn = f"nn{nn_nombre:d}"
    filepath_nn = filepath.with_name(
        f"{filepath.stem}_{str_ref_station_name}_{str_nn}{filepath.suffix}")

    return filepath_nn

def get_filepath_donnee_periode(
    client, ref_station_name, df_liste_stations=None,
    date_deb_periode=None, date_fin_periode=None,
    frequence=None, ref=False, nn_nombre=None):
    filename = f"donnees_{client.api}"
    if frequence is not None:
        filename += f"_{frequence}"

    str_ref_station_name = ref_station_name.lower().replace(' ', '')
    
    if nn_nombre is None:
        nn_nombre = len(df_liste_stations)
    str_nn = f"nn{nn_nombre:d}"

    str_date_deb_periode = ''
    if date_deb_periode is not None:
        str_date_deb_periode = '_' + get_str_date(date_deb_periode)
    str_date_fin_periode = ''
    if date_fin_periode is not None:
        str_date_fin_periode = '_' + get_str_date(date_fin_periode)

    str_station = "ref" if ref else "stations"
    
    filename += (f"_{str_ref_station_name}_{str_nn}"
                 f"{str_date_deb_periode}{str_date_fin_periode}"
                 f"_{str_station}.csv")
    parent = DATA_DIR / client.api
    parent.mkdir(parents=True, exist_ok=True)
    filepath = parent / filename
    
    return filepath

def compiler_donnee_des_stations_date(
    client, df_liste_stations, date, frequence=None):
    df = pd.DataFrame(dtype=float)
    for id_station in df_liste_stations.index:
        # Paramètres définissant la station, la date et le format des données
        params = {'id_station': id_station, 'date': date, 'format': FMT}
        
        # Requête pour la station
        section = 'station'
        response = demande(client, section, params=params, frequence=frequence)

        # DataFrame de la station
        s_station = response_text_to_frame(response).iloc[0]
        df_station = s_station.to_frame(id_station).transpose()

        # Compilation
        df = pd.concat([df, df_station])
        
    return df

def compiler_commandes_des_stations_periode(
    client, df_liste_stations, date_deb_periode, date_fin_periode,
    frequence=None):
    params = {
        'date-deb-periode': date_deb_periode,
        'date-fin-periode': date_fin_periode
    }
    id_commandes = {}
    for id_station in df_liste_stations.index:
        # Paramètres définissant la station, la date et le format des données
        params['id-station'] = id_station,
        
        # Requête pour la station
        section = 'commande-station'
        response = demande(client, section, params=params, frequence=frequence)

        # Récupération de l'identifiant de la commande pour la station
        id_commandes[id_station] = (
            response.json()['elaboreProduitAvecDemandeResponse']['return'])

    return id_commandes

def compiler_telechargement_des_stations_periode(
    client, df_liste_stations, date_deb_periode, date_fin_periode,
    frequence=None, read_csv_kwargs={},
    desired_status_code=201, timeout=300, retry_interval=5):
    id_commandes = compiler_commandes_des_stations_periode(
        client, df_liste_stations, date_deb_periode, date_fin_periode,
        frequence=frequence)
    
    df = pd.DataFrame(dtype=float)
    for id_station, id_cmde in id_commandes.items():    
                
        # Requête pour la station
        section = 'commande'
        params = {'id-cmde': id_cmde}

        start_time = time.time()
        while True:
            response = demande(client, section, params=params, frequence='fichier')
            
            # Check if the status code matches
            if response.status_code == desired_status_code:
                break
            else:
                print(f"Received status code {response.status_code}. Retrying...")
        
            # Check if the timeout has been reached
            if time.time() - start_time > timeout:
                raise requests.exceptions.Timeout(
                    f"Timeout reached after {timeout} seconds "
                    f"without receiving status code {desired_status_code}.")

            # Wait before the next attempt
            time.sleep(retry_interval)

        # DataFrame de la station
        df_station = response_text_to_frame(
            client, response, parse_dates=[client.time_label],
            index_col=[client.id_station_donnee_label, client.time_label],
            decimal=',', **read_csv_kwargs)
        
        # Compilation
        df = pd.concat([df, df_station])

    localisation_temps(df)

    inserer_noms_stations(client, df, df_liste_stations)
        
    return df      

def compiler_donnee_des_departements(
    client, df_liste_stations, frequence=None):
    id_departements = liste_id_stations_vers_liste_id_departements(
        df_liste_stations)
    df_toutes = pd.DataFrame(dtype=float)
    params = {'format': FMT}
    for id_dep in id_departements:
        # Requête pour la station
        section = 'paquet'
        params['id-departement'] = id_dep 
        response = demande(client, section, params=params, frequence=frequence)

        # DataFrame pour le département indexé par identifiant station et par date
        df_departement = response_text_to_frame(
            client, response, parse_dates=[client.time_label]).set_index(
            [client.id_station_donnee_label, client.time_label])
        
        # Compilation
        df_toutes = pd.concat([df_toutes, df_departement])

    # Sélection des stations de la liste
    try:
        df = df_toutes.loc[df_liste_stations.index]
    except KeyError:
        df_idx0 = df_toutes.index.levels[0]
        indices_commun = df_liste_stations.index.intersection(df_idx0)
        df = df_toutes.loc[indices_commun]
        indices_manquants = df_liste_stations.index.difference(df_idx0)
        warnings.warn(
            f"les stations {", ".join(indices_manquants.astype(str))} manquent.")

    # Suppression des duplicatas
    df = df[~df.index.duplicated(keep=False)]

    inserer_noms_stations(client, df, df_liste_stations)
        
    return df

def filtrer_stations_valides(client, df_brute):
    validite = (df_brute[client.ouvert_station_label] &
                df_brute[client.public_station_label] &
                (df_brute[client.type_station_label] != 5))
    
    df = df_brute.loc[validite].drop(
        [client.ouvert_station_label, client.public_station_label], axis=1)

    return df

def renommer_variables(client, df, frequence):
    labels_variables = {v: k for k, v in client.variables_labels[frequence].items()}
    df = df.rename(columns=labels_variables)

    return df

def inserer_noms_stations(client, df, df_liste_stations):
    ''' Insertion des noms des stations.'''
    id_stations_df = df.index.to_frame()[client.id_station_donnee_label]
    liste_noms_stations = [df_liste_stations.loc[_, client.station_name_label]
                           for _ in id_stations_df]
    df.insert(0, client.station_name_label, liste_noms_stations)

def get_str_date(date):
    try:
        s_date = pd.Timestamp(date, tz=TZ).isoformat().replace(
        "+00:00", "Z").replace('-', '').replace(':', '')
    except ValueError:
        s_date = pd.Timestamp(date).isoformat().replace(
        "+00:00", "Z").replace('-', '').replace(':', '')
    return s_date
    
def localisation_temps(df, tz=TZ):
    ''' Localisation UTC de l'indice temporel.'''
    index = [df.index.levels[0],
             pd.DatetimeIndex(df.index.levels[1], tz=TZ)]
    df.index = df.index.set_levels(index)

def convertir_unites(client, df):
    for variable, s in df.items():
        df.loc[:, variable] = client.variables_conversion_unites[variable](s)
    
    return df

    