"""Tests du bandeau restrictions sécheresse VigiEau (apps.veille.email).

Garde-fou de lisibilité : à tous les niveaux, le texte doit rester lisible
(contraste WCAG AA ≥ 4,5:1). Origine : en crise, fond rouge plein + texte gris
→ contraste 1,3:1, illisible.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apps.veille.email import (  # noqa: E402
    _VIGIEAU_COULEURS,
    _VIGIEAU_LEGENDE,
    _VIGIEAU_TEXTE,
    _bloc_restrictions_eau,
)
from meteo_socle.sources.vigieau import (  # noqa: E402
    NIVEAU_AUCUNE,
    RestrictionsEau,
    UsageRestriction,
    ZoneRestriction,
)

NIVEAUX = ("vigilance", "alerte", "alerte_renforcee", "crise")

TEXTE_CRISE = (
    "Sur décision du préfet : - soit mesures d'alerte renforcée, - soit interdiction.\r\n\r\n"
    "Un registre de prélèvement devra être renseigné hebdomadairement pour l'irrigation."
)


def _luminance(hexa: str) -> float:
    rgb = [int(hexa[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contraste(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _restrictions(niveau: str, description: str = TEXTE_CRISE) -> RestrictionsEau:
    usage = UsageRestriction(
        nom="Irrigation des cultures spéciales (maraîchage)",
        thematique="Irriguer",
        description=description,
    )
    zone = ZoneRestriction(
        type_ressource="SOU",
        niveau=niveau,
        nom_zone="Nappe test",
        usages_irrigation=(usage,),
        date_debut_arrete="2026-08-15",
    )
    return RestrictionsEau(commune_insee="35227", profil="exploitation", zones=[zone])


@pytest.mark.parametrize("niveau", NIVEAUX)
def test_contraste_lisible_a_tous_les_niveaux(niveau: str) -> None:
    c = _VIGIEAU_COULEURS[niveau]
    assert _contraste(_VIGIEAU_TEXTE, c["bg"]) >= 4.5
    assert _contraste(_VIGIEAU_LEGENDE, c["bg"]) >= 4.5
    # Pastille : libellé blanc sur couleur pleine.
    assert _contraste("#ffffff", c["fg"]) >= 4.5


@pytest.mark.parametrize("niveau", NIVEAUX)
def test_html_utilise_fond_clair_et_texte_fonce(niveau: str) -> None:
    html = _bloc_restrictions_eau(_restrictions(niveau))
    c = _VIGIEAU_COULEURS[niveau]
    assert f"background:{c['bg']}" in html
    # Aucune couleur de texte du bloc ne doit être illisible sur le fond.
    for coul in re.findall(r"(?<!-)color:(#[0-9a-fA-F]{6})", html):
        fond = c["fg"] if coul.lower() == "#ffffff" else c["bg"]
        assert _contraste(coul, fond) >= 4.5, (niveau, coul)


def test_crise_affiche_les_deux_mesures() -> None:
    html = _bloc_restrictions_eau(_restrictions("crise"))
    assert "Crise" in html
    assert "depuis le 15/08/2026" in html
    assert "Sur décision du préfet" in html
    assert "registre de prélèvement" in html
    # Deux paragraphes → liste à puces.
    assert html.count("<li ") == 2


def test_aucune_restriction_pas_de_bandeau() -> None:
    assert _bloc_restrictions_eau(None) == ""
    vide = RestrictionsEau(commune_insee="35227", profil="exploitation", zones=[])
    assert vide.niveau_souterrain == NIVEAU_AUCUNE
    assert _bloc_restrictions_eau(vide) == ""
