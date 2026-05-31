"""Helpers de style partagés entre apps (couleurs Wong, unités, sources).

Palette Bang Wong 2011 (Nature Methods) : choisie pour rester
distinguable par les daltoniens (deutéranopie + protanopie, ~8 % des
hommes). Utilisée à l'identique dans l'email Veille (cf.
``apps/veille/email.py``) — les apps doivent partager les mêmes codes
visuels.
"""

from __future__ import annotations

# ----- Palette Wong (référence visuelle inter-apps) -----
COULEUR_FROID = "#0072B2"  # bleu profond : T° min, froid
COULEUR_CHAUD = "#D55E00"  # vermillon : T° max, critique, déficit
COULEUR_PLUIE = "#56B4E9"  # bleu ciel : pluie, humidité
COULEUR_OK = "#009E73"  # vert bleuté : bilan positif, OK
COULEUR_WARNING = "#E69F00"  # orange : warning, anticiper
COULEUR_NEUTRE = "#7f8c8d"  # gris ardoise : T° moy, valeurs neutres

# Mapping niveau de carte → couleur d'accent du titre.
COULEURS_NIVEAU = {
    "info": COULEUR_FROID,
    "anticiper": COULEUR_WARNING,
    "critique": COULEUR_CHAUD,
}

# ----- Traçabilité (cohérence inter-apps, principe #5) -----
SOURCE_DEFAUT = "Open-Meteo · AROME France HD 1.3 km + ECMWF IFS 9 km"
METHODE_ETP = "FAO 56 Penman-Monteith horaire (socle)"


def unite_html(texte: str) -> str:
    """Span unité en gris discret (style identique à l'email Veille)."""
    return f'<span style="color:#aaa;font-weight:400;font-size:11px;">&nbsp;{texte}</span>'


def couleur_niveau(niveau: str) -> str:
    """Couleur d'accent du titre selon le niveau de carte."""
    return COULEURS_NIVEAU.get(niveau, COULEUR_NEUTRE)
