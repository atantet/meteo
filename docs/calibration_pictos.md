# Calibration des pictogrammes — mail Veille vs Météo-France

Registre **persistant** des comparaisons entre le picto de la grille 48 h du mail
(dérivé d'AROME par `code_wmo_diagnostic`/`serie_code_temps_mf`) et le picto
**officiel** de [MF.com](https://meteofrance.com/previsions-meteo-france/pleine-fougeres/35610).

**Les pictogrammes MF.com font foi** (référence). On ajuste notre dérivation pour
**coller à MF** ; les règles maison (ex. « éclaircies ») sont des **guides**, pas des
absolus — quand un guide s'écarte de MF, MF gagne.

But : repérer les **biais systématiques** et ajuster **progressivement** — jamais sur
un seul jour. Un écart isolé peut venir du run (AROME ~02 Z vs blend MF ~08 h) ou de
la curation MF (WWMF, absent du portail-api), pas forcément d'un seuil.

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
  (1 cas : 2026-06-20).
- **Correctif appliqué (2026-06-20)** : agrégation 6 h passée de « sévérité max »
  à **deux voies** — ciel sec mixte → éclaircies (partiellement nuageux), événement
  pluie/orage toujours signalé (`code_dominant_fenetre`). Devrait corriger le biais
  quand le ciel AROME était *mixte* sur la tranche ; à **vérifier** au prochain mail
  via le log `PICTO-DIAG` (si la tranche était *uniformément* couverte, le picto
  restera « couvert » — alors ce sera AROME plus pessimiste que MF, pas l'agrégation).

### Leviers restants (si le biais persiste après correctif agrégation)
- **Seuils** de nébulosité `(13, 38, 86)` — à rapprocher des octas MF seulement sur
  biais *répété* et documenté par les valeurs `PICTO-DIAG`.

## Journal des comparaisons

### 2026-06-23 (matin) — garde-fou orage validé ; biais cirrus corrigé

Garde-fou orage **OK** : aucun orage peint sur mardi ensoleillé (les seuls `95` sont
Mer soir sur les heures nuageuses ; l'heure claire en tête est gated). Vigilance
rouge captée (`max=Rouge | Canicule:Rouge`).

**Biais cirrus confirmé 3ᵉ jour → corrigé** : `tot 79-93 % / bas 0 / moy 0` = cirrus
seul. On rendait « partiellement nuageux », MF rend « peu nuageux/ensoleillé ». La
réduction « nuages hauts » ne visait que > 86 % (nébulosité 3) ; **élargie à ≥ 38 %**
(nébulosité 2) et **descendue à peu nuageux** (1, pas 2). Un vrai nuage bas n'est pas
touché. Effet : Mar matin (79 % cirrus) → peu nuageux (= MF), au lieu de partiel.

### 2026-06-22 (après-midi/soir) — garde-fou orage (overlay gated par le ciel)

Vigilance toujours rouge (`VIGIL-DIAG max=Rouge | émission=14:04Z | Canicule:Rouge`).
Écart picto orage : Lun soir nous ⛈️ Orage vs MF 🌤️ Peu nuageux.

**Vérification forecast (PAR HEURE MF)** : cette nuit MF = peu nuageux, « pas de
précipitations », 32→24° ; notre AROME = quasi-dégagé (2 %), 0 mm. **Les deux prévis
concordent (nuit calme)** → l'écart est une **différence de règle** (overlay Vigilance
sur ciel clair), pas un décalage de prévi. NB : AROME est à **0 mm sur TOUS** les
créneaux orage (Lun soir ET Mar a-m/soir) → drier que MF → **on ne peut pas brancher
l'orage sur la précip AROME** (sinon on perdrait l'orage de mardi).

**Correctif** : l'overlay orage Vigilance est désormais **gated par le ciel** — pas
peint sur une heure au ciel confirmé dégagé (code 0/1) ; gardé sur nuageux (≥ 2),
pluvieux (≥ 45) ou inconnu (`<NA>`, prudence). Effet : Lun soir (2 %) → plus d'orage
(= MF) ; Mardi (37-99 %) → orage gardé (= MF). Le **risque** reste au tableau Vigilance.

### 2026-06-22 (matin) — 5/5 sur les pictos + vigilance ROUGE captée

Pictos collent à MF.com sur toutes les tranches comparables :

| Tranche | codes | Nous | MF.com | |
|---|---|---|---|---|
| Lun matin | [0,0,0,0,0,0] | ☀️ Ensoleillé | ☀️ Ensoleillé | ✅ |
| Lun a-m | [0,0,0,95,95,95] | ⛈️ Orage (Vigi) | ⛈️ Orage | ✅ |
| Lun soir | [95,95,95,2,2,1] | ⛈️ Orage | ⛈️ Orage | ✅ |
| Mar matin | [0,0,2,2,2,1] | 🌤️ Peu nuageux | 🌤️ Peu nuageux | ✅ |
| Mar a-m | [0,0,0,0,0,0] | ☀️ Ensoleillé | ☀️ Ensoleillé | ✅ |

Les correctifs (unité % + agrégation représentative) éliminent les biais « trop
couvert » et « ⛅ partout ». L'orage Vigilance tombe pile (a-m + soir = MF).

**Vigilance rouge** : `VIGIL-DIAG dept 35 | max=Rouge | émission=2026-06-22T04:01Z |
Orages:Jaune, Canicule:Rouge`. La rouge a été **émise à 04:01 UTC** → captée par le
run de 04:40 UTC (sujet « Vigilance rouge : Canicule »). Le mail de la veille
après-midi (fetch 16:40 UTC) la précédait légitimement. Pas de trou : timing confirmé.

### 2026-06-21 (après-midi/soir) — correctifs validés ; écarts = doctrine/modèle

1er mail avec **tous** les correctifs (unité % + agrégation représentative).

| Tranche | codes | nébul moy/max | Nous | MF.com | Verdict |
|---|---|---|---|---|---|
| Dim soir | [1,2,0,2,2,2] | 60/100 | ⛅ Partiel. | ☁️ Couvert | seuil ? (1 pt) |
| Lun nuit | [2,2,0,0,0,0] | 28/100 | 🌤️ Peu nuageux | 🌤️ Peu nuageux | ✅ |
| Lun matin | [0,0,2,0,0,2] | 26/99 | 🌤️ Peu nuageux | 🌤️ Peu nuageux | ✅ |
| Lun a-m | [0,0,0,95,95,95] | 28/100 · 0 mm | ⛈️ Orage | 🌧️ Averse | doctrine |
| Lun soir | [95,95,95,95,2,2] | — | ⛈️ Orage | ⛈️ Orage | ✅ |

- **Raffinage validé** : Lun nuit/matin collent à MF (peu nuageux), plus de « ⛅ partout ».
- **Orage = Vigilance** (overlay 95) : fenêtre plus large que MF (a-m + soir vs averse + orage). Doctrine assumée ; soir ✅. À arbitrer si on veut resserrer sur MF.
- **Pluie Lun a-m** : AROME 0 mm vs averse MF → divergence de **modèle**, pas un seuil.
- **Dim soir** : nous partiel (60 %), MF couvert → **seuil** partiel/couvert à surveiller (1 seul point, pas d'ajustement).

### 2026-06-21 (matin) — 1ᵉʳ mail avec les 2 correctifs ; raffinage agrégation

`PICTO-DIAG` enfin en vraies fractions (ex. dim. matin tot moy/max **19/93 %**). Le
fix d'unité a **supprimé les « couvert » abusifs** ✅. Mais l'agrégation « mixte → 2 »
était trop brutale → on affichait **« partiellement nuageux » (⛅) partout**, 1 cran
au-dessus de MF (peu nuageux/ensoleillé sur des matinées à 20-33 % de nuages).

| Tranche | codes | nébul moy/max | Avant (mixte→2) | MF.com |
|---|---|---|---|---|
| Dim matin | [0,0,0,0,2,1] | 19/93 | ⛅ Partiel. | 🌤️ Peu nuageux |
| Dim a-m | [2,2,0,0,1,2] | 46/89 | ⛅ Partiel. | 🌤️ Peu nuageux |
| Lun matin | [0,0,2,2,0,0] | 33/99 | ⛅ Partiel. | ☀️ Ensoleillé |

**Raffinage** : ciel sec = niveau **représentatif (moyen)** au lieu de « mixte→2 »,
+ garde-fou éclaircies (jamais couvert plein s'il reste du soleil). Résultat attendu :
dim matin/a-m → **peu nuageux** (colle à MF), tout en gardant « 1 soleil + 5 couvert →
éclaircies ». À vérifier au prochain mail.

### 2026-06-20 (après-midi) — BUG D'UNITÉ trouvé via PICTO-DIAG

Le log `PICTO-DIAG` du run de l'après-midi montrait des nébulosités brutes de
**35, 99, 16…** (échelle 0-100) — or une fraction ≤ 1. **AROME sert la nébulosité
en % (0-100)**, mais la source la traitait en **fraction** (« frac » = identité),
puis le moteur picto ×100 → **35 % → 3500 → « couvert »**. C'est **la** cause du
biais « trop couvert ».

Contre-preuve décisive : ARPEGE tire **le même coverage** `TOTAL_CLOUD_COVER` du
**même WCS** et le déclare déjà `pct_frac` (÷100). Cause probable : héritage d'une
source antérieure (Open-Meteo → webservice → API) jamais revérifié à la bascule
ADR-0021 ; le fixture synthétique (0,5 → 0,5) ne pouvait pas l'attraper.

**Correctif** : `cloud_cover` total/bas/moyen passés en `pct_frac` (÷100) dans
`meteofrance_arome.py` ; fixture + test de régression inversés ; le ÷100 rend les
codes corrects (35 % → peu nuageux). À **vérifier au prochain mail** : les pictos
devraient coller bien mieux à MF.com (moins de « couvert » sur ciel partiel).


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
