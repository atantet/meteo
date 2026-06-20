"""Pictogrammes météo basés sur les codes WMO 4677 (Open-Meteo).

Mappe les codes ``weather_code`` à des icônes SVG du jeu **MET Norway /
yr** (Institut météorologique norvégien, MIT — cf. ``assets/yr/LICENSE``,
<https://github.com/metno/weathericons>). Choix cohérent avec l'algorithme
de symbole temps de MET Norway porté dans le socle (cf. ADR-0013) : même
service météo national pour le fond (classification) et la forme (icônes).

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
ICONES_DIR = _REPO_ROOT / "assets" / "yr"

# Mapping WMO 4677 → nom de symbole yr (variante JOUR / neutre, sans .svg).
# yr n'a pas de « bruine » : les codes 51-55 sont rendus en pluie. Les
# variantes nuit éventuelles sont dans WMO_VERS_ICONE_NUIT.
WMO_VERS_ICONE: dict[int, str] = {
    0: "clearsky_day",
    1: "fair_day",
    2: "partlycloudy_day",
    3: "cloudy",
    45: "fog",
    48: "fog",
    51: "lightrain",
    53: "lightrain",
    55: "rain",
    56: "lightsleet",
    57: "sleet",
    61: "lightrain",
    63: "rain",
    65: "heavyrain",
    66: "lightsleet",
    67: "heavysleet",
    71: "lightsnow",
    73: "snow",
    75: "heavysnow",
    77: "lightsnow",
    80: "lightrainshowers_day",
    81: "rainshowers_day",
    82: "heavyrainshowers_day",
    85: "lightsnowshowers_day",
    86: "heavysnowshowers_day",
    95: "rainandthunder",
    96: "heavyrainandthunder",
    99: "heavyrainandthunder",
}

# Variantes nuit yr (soleil → lune) pour les seuls symboles qui en ont une :
# ciel clair, peu nuageux, partiellement nuageux, et les averses (pluie/neige).
# Les codes neutres yr (cloudy, fog, pluie/neige continues, orage) n'ont pas de
# variante nuit → nom_icone retombe sur l'icône jour/neutre, qui reste lisible.
WMO_VERS_ICONE_NUIT: dict[int, str] = {
    0: "clearsky_night",
    1: "fair_night",
    2: "partlycloudy_night",
    80: "lightrainshowers_night",
    81: "rainshowers_night",
    82: "heavyrainshowers_night",
    85: "lightsnowshowers_night",
    86: "heavysnowshowers_night",
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

# Hiérarchie de sévérité (utilisée pour la voie « événement » de l'agrégation :
# signaler le code le plus impactant). Plus grand = plus sévère / impactant.
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


def nom_icone(code: int, nuit: bool = False) -> str:
    """Renvoie le nom de symbole yr (sans ``.svg``) pour un code WMO.

    Si ``nuit=True`` et qu'une variante nuit existe (`WMO_VERS_ICONE_NUIT`),
    la variante nuit est utilisée (soleil → lune). Sinon, fallback sur
    l'icône jour/neutre (pluies/neiges continues et orages n'ont pas de
    variante nuit).
    """
    code_int = int(code)
    if nuit and code_int in WMO_VERS_ICONE_NUIT:
        return WMO_VERS_ICONE_NUIT[code_int]
    return WMO_VERS_ICONE.get(code_int, "not-available")


def libelle(code: int) -> str:
    """Libellé FR humain pour un code WMO."""
    return WMO_VERS_LIBELLE.get(int(code), f"Code météo {code}")


def chemin_icone(code: int, nuit: bool = False) -> Path:
    """Chemin absolu du fichier icône SVG yr.

    Les icônes yr sont toutes en SVG (cf. `assets/yr/`). Fallback sur
    ``not-available.png`` si le symbole n'a pas de fichier (cas improbable).
    """
    nom = nom_icone(code, nuit=nuit)
    svg = ICONES_DIR / f"{nom}.svg"
    if svg.exists():
        return svg
    return ICONES_DIR / "not-available.png"


def _mime_pour_chemin(chemin: Path) -> str:
    """Renvoie le type MIME utile à un data URI selon l'extension."""
    return "image/svg+xml" if chemin.suffix.lower() == ".svg" else "image/png"


def icone_bytes(code: int, nuit: bool = False) -> bytes | None:
    """Renvoie les bytes de l'icône pour st.image() ou équivalent.

    Évite les soucis de résolution de chemin (notamment sur Streamlit
    Cloud où ``Path.exists()`` peut être trompeur). Retourne None si
    l'icône n'existe pas, dans ce cas l'appelant doit fallback texte.
    """
    chemin = chemin_icone(code, nuit=nuit)
    if not chemin.exists():
        return None
    return chemin.read_bytes()


def icone_base64(code: int, nuit: bool = False) -> str:
    """Renvoie l'icône encodée base64 prête pour ``<img src="data:...">``.

    Retourne une chaîne du type ``data:image/png;base64,…`` (ou
    ``data:image/svg+xml;base64,…`` selon l'extension du fichier
    source). Quand l'icône demandée n'existe pas, fallback vers
    ``not-available.png``.
    """
    chemin = chemin_icone(code, nuit=nuit)
    if not chemin.exists():
        chemin = ICONES_DIR / "not-available.png"
    data = base64.b64encode(chemin.read_bytes()).decode("ascii")
    return f"data:{_mime_pour_chemin(chemin)};base64,{data}"


def codes_dominants_par_jour(
    prevision_horaire: pd.DataFrame,
    tz_locale: str = "Europe/Paris",
    heure_debut_diurne: int = 8,
    heure_fin_diurne: int = 20,
) -> list[tuple[pd.Timestamp, int]]:
    """Agrège les codes WMO horaires en code dominant par jour local.

    Restreint la fenêtre aux heures diurnes (défaut 8h-20h locales) pour
    refléter ce que perçoit l'utilisateur de jour. Délègue à
    ``code_dominant_fenetre`` (agrégation à deux voies : un événement pluie/orage
    est signalé, sinon le ciel sec reflète les éclaircies).

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
    """Choisit le code représentatif d'une fenêtre horaire (agrégation à deux voies).

    Un picto de tranche doit **refléter toutes les heures, éclaircies comprises** —
    pas seulement la plus chargée. Deux voies :

    - **Événement** (brouillard / précip / orage, code ≥ 45) : si une heure en porte un,
      on le **signale** (sévérité max). Ne jamais cacher une averse ou un orage.
    - **Ciel sec** (codes 0-3 : ensoleillé / peu nuageux / partiellement nuageux /
      couvert) : on reflète la **variabilité**. Un ciel **mixte** (du soleil ET des
      nuages dans la fenêtre) → **partiellement nuageux** (éclaircies) ; couvert plein
      seulement si **toutes** les heures sont couvertes ; clair seulement si la fenêtre
      reste dans le registre ensoleillé.

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
    # Voie « événement » : brouillard/précip/orage (code ≥ 45) → sévérité max.
    significatifs = codes_valides[codes_valides >= 45]
    if not significatifs.empty:
        severites = significatifs.map(lambda c: WMO_SEVERITE.get(int(c), 0))
        return int(significatifs.loc[severites.idxmax()])
    # Voie « ciel sec » : refléter les éclaircies.
    lo, hi = int(codes_valides.min()), int(codes_valides.max())
    if hi <= 1:
        return hi  # tout dans le clair (ensoleillé / peu nuageux)
    if lo >= 3:
        return 3  # toutes les heures couvertes → couvert
    return 2  # mixte (soleil + nuages) → partiellement nuageux (éclaircies)
