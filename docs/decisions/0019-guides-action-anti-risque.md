# ADR-0019 — Guides de décision : action anti-risque, pas de permissif

Statut : **Accepté**.

## Contexte

Les guides de la semaine (App 2, `apps/operationnelle/decisions.py`) sont des
invitations rattachées à un signal météo. À la revue (2026-06-13), deux écarts
de doctrine sont apparus :

1. Le guide « **Nuits chaudes ≥ 12 °C → laisser les portes ouvertes la nuit** »
   dit ce qu'on **peut relâcher** (permissif/confort), pas une action pour
   **parer un risque**. Or l'attente est : *un guide dit quoi faire pour éviter
   un risque important*, jamais « ce que tu peux éviter de faire ».
2. Le découpage saisonnier « fenêtre sèche » (hiver) / « fenêtre pluvieuse »
   (été) pour le travail du sol était un **réglage calendaire pragmatique non
   validé** (`config/exploitation.yaml`, flag « à recalibrer par usage »).

## Décision

**1. Principe — un guide = action de mitigation d'un risque.** On supprime les
guides permissifs ; chaque guide actif porte une action contre un risque (gel →
purger l'irrigation, froid → voiles P17, nuits fraîches → fermer, déficit →
irriguer, fortes chaleurs → bassiner/ombrer, nuits douces → aérer/surveiller
maladies). L'action reste une **invitation** (cf. ADR-0014 / principe « pas
d'injonction »), mais risque-orientée.

**2. Suppression du guide « nuits chaudes / aération ≥ 12 °C ».** Le risque réel
des nuits douces (≥ 15 °C → maladies fongiques) est déjà couvert, **en action**,
par `regle_risque_maladie` (aérer, surveiller oïdium/botrytis/mildiou). Les
seuils `seuils_tunnel.aeration_nuit_*` sont retirés.

**3. Fenêtre pluvieuse — risque explicite.** Message recadré : « travailler le
sol **avant** : il sera détrempé, intervention bloquée » (l'action et le risque
évité sont nommés).

**4. Saisons travail du sol — validées sur climatologie ERA5.** Bilan mensuel
**pluie − ET0 FAO** au point, ERA5 1991-2020 (30 ans) : surplus (sol en
recharge) d'**octobre à mars**, déficit d'avril à septembre. Octobre (+32 mm,
comparable à novembre) relevait à tort de la « fenêtre pluvieuse ». Corrigé :

- `travail_sol_recherche_fenetre_seche: [10, 11, 12, 1, 2, 3]`
- `travail_sol_recherche_fenetre_pluvieuse: [4, 5, 6, 7, 8, 9]`

## Conséquences

- Moins de bruit : plus de guide permissif ; la fenêtre sèche colle à la saison
  où le sol est réellement gorgé (octobre inclus).
- Provenance tracée : le découpage saisonnier n'est plus un dire d'expert non
  sourcé mais un résultat climatologique (ERA5 1991-2020), conforme à la
  doctrine « provenance des données ».
- Limite assumée : le découpage reste **calendaire** (aveugle à une saison
  atypique / aux mois charnières). Un raffinement adaptatif (déclencher la
  fenêtre sèche selon la pluie récente / l'humidité de sol réelle) reste
  possible plus tard ; non retenu en v0 pour rester simple.
- La carte « fermer la nuit » (≤ 3 °C, anti-froid) est conservée.
