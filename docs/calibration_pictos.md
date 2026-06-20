# Calibration des pictogrammes — mail Veille vs Météo-France

Registre **persistant** des comparaisons entre le picto de la grille 48 h du mail
(dérivé d'AROME par `code_wmo_diagnostic`/`serie_code_temps_mf`) et le picto
**officiel** de [MF.com](https://meteofrance.com/previsions-meteo-france/pleine-fougeres/35610).

But : repérer les **biais systématiques** et ajuster **progressivement** les seuils —
jamais sur un seul jour. Un écart isolé peut venir du run (AROME ~02 Z vs blend MF
~08 h) ou de la curation MF (WWMF, absent du portail-api), pas forcément d'un seuil.

## Rappel du moteur

| Nébulosité totale | Icône | Libellé |
|---|---|---|
| ≤ 13 % | `Sun` ☀️ | Ensoleillé |
| ≤ 38 % | `LightCloud` 🌤️ | Peu nuageux |
| ≤ 86 % | `PartlyCloud` ⛅ | Partiellement nuageux |
| > 86 % | `Cloud` ☁️ | Couvert |

- Seuils : `_SEUILS_NEBULOSITE_PCT = (13, 38, 86)` (`temps_sensible.py`).
- Réduction cirrus : `Cloud` → `PartlyCloud` si pluie nulle **et** couches basse + moyenne ≤ 13 %.
- Agrégation 6 h : **sévérité max** (`code_dominant_fenetre`) — le pire des 6 créneaux.
- Orage : **Vigilance seule** (jamais dérivé du modèle).

## Synthèse des biais observés (à ce jour)

- **Tendance « trop couvert »** sur les tranches que MF cure en « peu nuageux »
  (1 cas : 2026-06-20). **À confirmer** sur d'autres jours avant tout ajustement.
- Hypothèses à départager (manque les valeurs horaires sous-jacentes) :
  agrégation max 6 h trop pessimiste **ou** AROME réellement plus couvert que MF.

## Journal des comparaisons

### 2026-06-20 — Pleine-Fougères (mail matin, run AROME ~02 Z ; MF.com relevé ~08 h)

| Tranche | MF.com | Mail | Notre code | Écart |
|---|---|---|---|---|
| Sam. 20 matin | Peu nuageux · 22° | Couvert ☁️ · 15/21° | `Cloud` (>86 %) | **trop couvert (+1-2)** |
| Sam. 20 après-midi | Peu nuageux · 25° | Couvert ☁️ · 22/24° | `Cloud` (>86 %) | **trop couvert (+1-2)** |
| Sam. 20 soir | Dégagé · 21° | Peu nuageux ⛅ · 22/24° | `PartlyCloud` (38-86 %) | léger |
| Dim. 21 matin | Peu nuageux · 25° | Peu nuageux 🌤️ · 18/26° | `LightCloud`/`PartlyCloud` | ✓ |
| Dim. 21 après-midi | Peu nuageux · 31° | Peu nuageux ⛅ · 28/32° | `PartlyCloud` | ✓ |
| Dim. 21 soir | (n/d) | Ensoleillé ☀️ · 26/32° | `Sun` | — |

Notes : samedi décroche (couvert) mais pas dimanche → la réduction cirrus ne s'est
pas déclenchée samedi (couches basse/moyenne non dégagées). Pas pluie partout (0 %).
Manque : cloud_cover horaire (total/bas/moyen) par tranche pour trancher agrégation
vs réalité AROME → **instrumenter avant de toucher aux seuils**.
