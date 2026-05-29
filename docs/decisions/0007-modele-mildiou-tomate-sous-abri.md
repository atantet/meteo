# ADR-0007 — Modèle de risque mildiou tomate (sous abri)

## Statut

Accepté — 2026-05-29
*Note : v0 indicative ; à recalibrer après une saison de retour terrain
sur les périodes effectivement déclenchées vs symptômes observés.*

## Contexte

Le **mildiou de la tomate** (*Phytophthora infestans*, même agent que
le mildiou pomme de terre) est la principale menace cryptogamique sur
les tomates de plein air et sous abri ouvert en climat océanique humide
breton. Sous abri (tunnel froid, serre froide), la pression reste
réelle dès que l'aération est insuffisante ou que les portes restent
ouvertes les nuits humides. L'objectif de cet indice est d'aider
l'utilisateur à **anticiper** les fenêtres à risque pour décider d'une
aération, d'un effeuillage, ou d'un traitement cuivre — pas de prescrire.

**Contraintes du projet** :
- Indicateur calculable à partir des variables horaires standard
  (T° 2 m, HR) accessibles via Open-Meteo prévision (Veille, Op) et
  l'archive ERA5 (Climato).
- Pas de capteur LWD ni d'enregistreur sous abri en v0 (cf. ADR-0005).
  Données utilisées = micro-climat **extérieur** maille ~25 km.
- Respect des principes structurants : transparence des formules,
  pas de boîte noire, information non prescriptive.
- Cohérence inter-apps : même calcul socle pour Veille, Op, Climato
  (principe de cohérence-méthode).

Trois familles de modèles candidats ont été examinées :

| Modèle | Année | Inputs | Sortie | Adapté ? |
|---|---|---|---|---|
| Smith periods | 1956 | T_min, HR | Période oui/non | Oui — simple, lisible, doctrine UK pertinente climat tempéré humide |
| Hyre + Wallin (Blitecast) | 1954-75 | T_min 7-10 j moy., HR, pluie | Score 0-7 | Plus précis mais paramétrisation lourde |
| Mileos® | post-1990 | Multi-inputs propriétaires | Score risque | Boîte noire — viole le principe #6 |

## Décision

Le socle implémente le **modèle Smith periods (1956)** comme indicateur
v0 unique, en première intention sur tomate sous abri.

### Définition opérationnelle

Une **« période de Smith »** est détectée sur une fenêtre de 2 jours
calendaires consécutifs *A* et *B* (heures locales) si **les deux**
satisfont :

- Température minimale journalière **T_min ≥ 10 °C**
- Nombre d'heures avec **humidité relative ≥ 90 %** ≥ **11 heures**
  sur la journée

La période est étiquetée sur le jour *B* (jour qui clôt la fenêtre).
L'indicateur sortant est binaire (`smith_period: bool`) horodaté à la
journée locale, plus un compteur cumulé `nb_smith_periods` sur la
fenêtre d'analyse (7 j pour Op, 72 h pour Veille, 30 ans pour Climato).

### Convention HR

Open-Meteo et ERA5 fournissent l'HR en pourcentage, le socle l'expose
en fraction 0-1 (cf. conventions `meteo_socle.sources`). Le seuil 90 %
devient donc `HR ≥ 0.90` dans le code.

### Convention horaire

Le décompte des heures HR ≥ 90 % se fait sur le **jour calendaire
local** (Europe/Paris), pas UTC. La nuit du 14 au 15 août est attribuée
au jour 15 pour la part 00-06 et au jour 14 pour la part 18-23 — le
modèle Smith historique compte sur jour calendaire, on s'y aligne.

### Apps consommatrices

| App | Fenêtre | Sortie présentée |
|---|---|---|
| Veille | 72 h à venir | Flag "Smith period probable J+1 / J+2" + heures HR≥90 % par jour |
| Opérationnelle | 7 j prévision | Colonne ✓/✗ Smith par jour, info-bulle critère détaillé |
| Climato | 1991-2020 | Nb annuel de Smith periods + heat-map mensuelle |

## Justification

- **Smith en première intention** : (i) trois variables horaires simples
  uniquement (T°, HR), aucun input pénible à dériver ; (ii) lisibilité
  totale du critère pour l'utilisateur, alignement principe #1
  (accompagner) et #5 (transparence) ; (iii) doctrine établie en UK et
  en France (CTIFL référence Smith dans plusieurs fiches) sur climats
  tempérés humides océaniques ; (iv) reproductibilité triviale — pas de
  paramètre à calibrer.
- **Pas de Blitecast en v0** : sortie 0-7 plus riche mais paramétrisation
  (moyennes mobiles, seuils pluie en pouces) lourde à documenter pour un
  gain de précision marginal sans validation locale.
- **Pas de Mileos** : modèle propriétaire, viole le principe #6 (pas de
  boîte noire).
- **Indépendance de l'ADR-0005 (LWD)** : Smith utilise HR comme proxy
  d'humectation, pas le LWD Magarey. C'est moins fin mais plus simple
  pour une v0. Une v1 ultérieure pourra substituer un critère
  "h LWD-Magarey ≥ 11" au "h HR ≥ 90 %" si validation montre intérêt.

## Conséquences

- **Donnée HR maille 25 km** (ERA5 / Open-Meteo) ≠ HR sous abri. Le
  modèle Smith calibré sur micro-climat sous-estime sans doute le risque
  en abri ouvert (HR plus élevée dedans) et le surestime en abri fermé
  bien aéré. À documenter en clair dans chaque app. Calibration locale
  envisageable post-saison N+1 si décalage observé.
- **Pas de validation locale en v0** : on présente comme indicateur
  *informationnel*, pas comme alerte. L'utilisateur conserve sa
  décision phytosanitaire.
- **Code partagé socle** : implémentation dans
  `meteo_socle.indices.mildiou.smith_periods(quotidien, h_min=11,
  t_min_celsius=10.0, hr_seuil=0.90)`. Tests unitaires sur cas
  canoniques (vraie/fausse période, jours limites).
- **Ajustabilité** : les trois seuils (T_min, HR, h_min) sont
  paramétrables via config, défauts = valeurs Smith historiques. Permet
  ré-étalonnage local sans changer le code.
- **Surveillance bibliographique** : doctrine récente (Eyal 2019, FAO
  Crop Pathology Lab) revisite les seuils selon variétés tomate. Une
  mise à jour structurante sera tranchée en ADR successeur.

## Références

- **Smith, L.P., 1956.** *Potato blight forecasting by 90 per cent
  humidity criteria*. **Plant Pathology** 5, 83-87.
  DOI: 10.1111/j.1365-3059.1956.tb00091.x *[à vérifier]*.
- **Royal Horticultural Society / ADAS** : Smith Periods continue d'être
  utilisé en doctrine UK contemporaine.
- **CTIFL** : fiches mildiou tomate citent Smith en référence
  historique (avec Mileos en production).
- **Sentelhas, P.C., Gillespie, T.J., 2008.** *Estimating hourly net
  radiation for leaf wetness duration using the Penman-Monteith
  equation.* **Theoretical and Applied Climatology**. Cadre cousin
  utile pour v1 (substitution HR → LWD-Magarey).
