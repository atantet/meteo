# ADR-0017 — Proba pluie de la semaine : proba officielle MF calibrée (signal autonome)

Statut : **Accepté** · amende [ADR-0014](0014-prevision-officielle-mf-veille.md) et
[ADR-0015](0015-fusion-app2-dans-mail-veille.md) (canal proba de la semaine).

## Contexte

La section « La semaine » (tendance 10 j du mail Veille) affichait une **proba
pluie maison** : fraction de membres **ECMWF IFS-ENS** au cumul ≥ 1 mm/6 h
(`obtenir_proba_ensemble`, cf. ADR-0014). Ce choix avait été fait pour éviter le
champ `precipitation_probability` d'Open-Meteo (GEFS **opaque**).

Deux constats nouveaux (juin 2026) :

1. La **prévision officielle MF** (webservice, déjà récupérée pour la partie
   48 h d'App 1) porte une proba pluie **calibrée** `probability_forecast`
   couvrant **tout J+10** (vérifié au point : 42 fenêtres 3 h puis 6 h, alignées
   minuit UTC). Donc disponible **sans fetch supplémentaire**.
2. Migrer l'ensemble ECMWF en direct (opendata) coûterait **~1,9 Go/run** (tp
   des 51 membres, champs globaux) — disproportionné pour une décoration.

La proba MF n'est **ni de l'ARPEGE** (déterministe, pas de proba ; et la proba
va au-delà des 102 h d'ARPEGE) **ni de l'ECMWF** (c'est un blend officiel MF).
L'étiqueter comme l'un des deux modèles serait une fausse attribution.

## Décision

La proba pluie de la semaine devient la **proba officielle MF calibrée**, traitée
comme un **signal autonome, indépendant des modèles de ciel** :

- Source : `PrevisionMF.proba_bins` (bins UTC → %), parsée depuis
  `probability_forecast` et passée à `executer_semaine(proba_mf=…)`. Aucun appel
  réseau de plus (réutilise le fetch d'App 1).
- Agrégation : `proba_max_par_fenetre` — `max` des bins (≤ 6 h, alignés minuit)
  par fenêtre 12 h Jour [06,18) / Nuit [18,06) UTC. Aucune densification horaire
  (le `max` est invariant). La proba **sort du df modèle** : `agreger_par_fenetre`
  ne reçoit plus que des champs modèle et un dict proba-par-fenêtre.
- Affichage : **une seule fois par cellule, en tête** (ligne ARPEGE quand il
  couvre le jour, J0-J4 ; sinon ECMWF, J5-J10) → se lit comme la proba de la
  période. Légende et sources nomment « MF officielle ».
- La proba maison **ECMWF IFS-ENS est abandonnée** côté semaine.
  `obtenir_proba_ensemble` reste dans le socle (non appelée) ; suppression
  différée.

## Conséquences

**Positif**
- **Calibrée** : la référence pour notre point, vs une proba maison non calibrée.
- **Une seule méthode pluie** App 1 + semaine (cohérent avec la doctrine
  « une seule méthode par phénomène »).
- **Supprime la dette ensemble** : plus de dépendance à l'Ensemble API Open-Meteo
  ni de tentation opendata à 1,9 Go/run.
- Coût marginal nul (proba déjà fetchée).

**Négatif / assumé**
- **Opacité de fabrique** : la dérivation de `probability_forecast` (blend
  PEARP + CEP, calibrage) n'est pas documentée — c'est une boîte noire, en
  tension avec le principe « pas de boîte noire ». Assumé par l'**étiquette
  honnête « MF officielle »** : on nomme la source faisant autorité, on ne
  prétend pas que c'est notre calcul. Tranché en faveur de la calibration et de
  l'unicité de méthode (cohérent avec ADR-0014 D9, qui assume déjà le webservice
  MF comme source d'autorité opaque pour le *verdict*).
- **Dépendance accrue au webservice MF** : si injoignable, la proba de la semaine
  est simplement **omise** (dégradation gracieuse, `proba_mf` vide en repli
  ARPEGE) — la tendance reste affichée.

**Validation** (discipline « vérifier les substitutions ») : comparaison à notre
point sur 37 bins jusqu'à J+10, MF moy 9 % vs ENS moy 7 %, écart absolu moyen
6 pts, corrélation 0,64 — même régime, aucun red flag (période sèche ;
re-vérifier en épisode pluvieux).
