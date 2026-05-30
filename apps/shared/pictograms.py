"""Pictogrammes météo basés sur les codes WMO 4677 (Open-Meteo).

Mappe les codes ``weather_code`` retournés par Open-Meteo à des
fichiers PNG de la suite **Meteocons** (Bas Milius, MIT — cf.
``assets/meteocons/LICENSE``).

Codes WMO 4677 résumés (cf. https://open-meteo.com/en/docs) :

- 0           : Ciel clair
- 1, 2, 3     : Principalement clair / partiellement nuageux / couvert
- 45, 48      : Brouillard / brouillard givrant
- 51, 53, 55  : Bruine légère / modérée / forte
- 56, 57      : Bruine verglaçante
- 61, 63, 65  : Pluie légère / modérée / forte
- 66, 67      : Pluie verglaçante
- 71, 73, 75  : Neige légère / modérée / forte
- 77          : Cristaux de neige
- 80, 81, 82  : Averses légères / modérées / fortes
- 85, 86      : Averses de neige
- 95          : Orage
- 96, 99      : Orage avec grêle

Utilisé par App 1 Veille (bande pictos en tête du mail) et App 2 Op
(comparaison ARPEGE vs IFS dashboard).

API publique :
- ``nom_icone(code)`` → nom du fichier PNG
- ``libelle(code)`` → libellé FR du code WMO
- ``chemin_icone(code)`` → chemin absolu de l'icône
- ``icone_base64(code)`` → data URI pour ``<img src="data:...">``
- ``code_dominant_fenetre(série)`` → max sévérité d'une fenêtre
- ``codes_dominants_par_jour(df, tz_locale)`` → liste de (date, code)
"""

from __future__ import annotations

import base64
from pathlib import Path

import pandas as pd

# Racine repo + dossier des icônes packagées.
_REPO_ROOT = Path(__file__).resolve().parents[2]
ICONES_DIR = _REPO_ROOT / "assets" / "meteocons"

# Mapping WMO → nom de fichier icône (sans extension .png).
WMO_VERS_ICONE: dict[int, str] = {
    0: "clear-day",
    1: "partly-cloudy-day",
    2: "partly-cloudy-day",
    3: "overcast-day",
    45: "fog-day",
    48: "fog-day",
    51: "drizzle",
    53: "drizzle",
    55: "drizzle",
    56: "drizzle",
    57: "drizzle",
    61: "partly-cloudy-day-rain",
    63: "rain",
    65: "rain",
    66: "rain",
    67: "rain",
    71: "partly-cloudy-day-snow",
    73: "snow",
    75: "snow",
    77: "snow",
    80: "partly-cloudy-day-rain",
    81: "rain",
    82: "rain",
    85: "partly-cloudy-day-snow",
    86: "snow",
    95: "thunderstorms",
    96: "thunderstorms-rain",
    99: "thunderstorms-rain",
}

# Libellés FR par code WMO (info-bulle / texte alt).
WMO_VERS_LIBELLE: dict[int, str] = {
    0: "Ciel clair",
    1: "Principalement clair",
    2: "Partiellement nuageux",
    3: "Couvert",
    45: "Brouillard",
    48: "Brouillard givrant",
    51: "Bruine légère",
    53: "Bruine modérée",
    55: "Bruine dense",
    56: "Bruine verglaçante légère",
    57: "Bruine verglaçante dense",
    61: "Pluie légère",
    63: "Pluie modérée",
    65: "Pluie forte",
    66: "Pluie verglaçante légère",
    67: "Pluie verglaçante forte",
    71: "Neige légère",
    73: "Neige modérée",
    75: "Neige forte",
    77: "Cristaux de neige",
    80: "Averses légères",
    81: "Averses modérées",
    82: "Averses violentes",
    85: "Averses de neige légères",
    86: "Averses de neige fortes",
    95: "Orage",
    96: "Orage avec petite grêle",
    99: "Orage avec grosse grêle",
}

# Hiérarchie de sévérité (utilisée pour l'agrégation "max severity"
# par jour). Plus grand = plus sévère / impactant.
WMO_SEVERITE: dict[int, int] = {
    0: 0,
    1: 1,
    2: 2,
    3: 3,
    45: 4,
    48: 4,
    51: 5,
    53: 5,
    55: 5,
    56: 6,
    57: 6,
    61: 7,
    63: 8,
    65: 9,
    66: 9,
    67: 9,
    71: 7,
    73: 8,
    75: 9,
    77: 6,
    80: 7,
    81: 8,
    82: 9,
    85: 8,
    86: 9,
    95: 10,
    96: 11,
    99: 11,
}


def nom_icone(code: int) -> str:
    """Renvoie le nom de fichier icône Meteocons pour un code WMO."""
    return WMO_VERS_ICONE.get(int(code), "not-available")


def libelle(code: int) -> str:
    """Libellé FR humain pour un code WMO."""
    return WMO_VERS_LIBELLE.get(int(code), f"Code météo {code}")


def chemin_icone(code: int) -> Path:
    """Chemin absolu du PNG icône pour un code WMO."""
    return ICONES_DIR / f"{nom_icone(code)}.png"


def icone_bytes(code: int) -> bytes | None:
    """Renvoie les bytes du PNG icône pour st.image() ou équivalent.

    Évite les soucis de résolution de chemin (notamment sur Streamlit
    Cloud où ``Path.exists()`` peut être trompeur). Retourne None si
    l'icône n'existe pas, dans ce cas l'appelant doit fallback texte.
    """
    chemin = chemin_icone(code)
    if not chemin.exists():
        chemin = ICONES_DIR / "not-available.png"
    if not chemin.exists():
        return None
    return chemin.read_bytes()


def icone_base64(code: int) -> str:
    """Renvoie le PNG icône encodé base64 prêt pour ``<img src="data:...">``.

    Retourne une chaîne du type
    ``data:image/png;base64,iVBORw0KGgo...``.
    """
    chemin = chemin_icone(code)
    if not chemin.exists():
        chemin = ICONES_DIR / "not-available.png"
    data = base64.b64encode(chemin.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def codes_dominants_par_jour(
    prevision_horaire: pd.DataFrame,
    tz_locale: str = "Europe/Paris",
    heure_debut_diurne: int = 8,
    heure_fin_diurne: int = 20,
) -> list[tuple[pd.Timestamp, int]]:
    """Agrège les codes WMO horaires en code dominant par jour local.

    Restreint la fenêtre aux heures diurnes (défaut 8h-20h locales) pour
    refléter ce que perçoit l'utilisateur de jour. Choisit le code de
    **sévérité maximale** par jour (privilégie la signalisation d'un
    épisode pluvieux ponctuel sur la moyenne).

    Parameters
    ----------
    prevision_horaire :
        DataFrame indexé UTC avec colonne ``weather_code``.
    tz_locale :
        Fuseau pour découper les jours calendaires.
    heure_debut_diurne, heure_fin_diurne :
        Bornes locales (incluse / exclue).

    Returns
    -------
    list[(date, code)]
        Triées chronologiquement.
    """
    if prevision_horaire.empty or "weather_code" not in prevision_horaire.columns:
        return []
    horaire_loc = prevision_horaire.copy()
    horaire_loc.index = pd.DatetimeIndex(horaire_loc.index).tz_convert(tz_locale)
    horaire_diurne = horaire_loc[
        (horaire_loc.index.hour >= heure_debut_diurne) & (horaire_loc.index.hour < heure_fin_diurne)
    ]
    par_jour: dict[pd.Timestamp, int | None] = {}
    for jour, grp in horaire_diurne.groupby(horaire_diurne.index.normalize()):
        codes = grp["weather_code"]
        code = code_dominant_fenetre(codes)
        if code is not None:
            par_jour[jour] = code
    return sorted(par_jour.items())


def code_dominant_fenetre(codes_horaires: pd.Series) -> int | None:
    """Choisit le code représentatif d'une fenêtre horaire.

    Heuristique : prend le code avec la **sévérité maximale**
    (impacte plus l'utilisateur de signaler la pluie cachée que de
    montrer un soleil moyen).

    Parameters
    ----------
    codes_horaires :
        Série de codes WMO sur la fenêtre (peut contenir des NaN).

    Returns
    -------
    int | None
        Code WMO retenu, ou ``None`` si la série est vide / tout NaN
        (cas typique d'un modèle qui ne fournit pas weather_code,
        ex. ECMWF IFS04 sur Open-Meteo).
    """
    codes_valides = codes_horaires.dropna().astype(int)
    if codes_valides.empty:
        return None
    severites = codes_valides.map(lambda c: WMO_SEVERITE.get(int(c), 0))
    idx_max = severites.idxmax()
    return int(codes_valides.loc[idx_max])
