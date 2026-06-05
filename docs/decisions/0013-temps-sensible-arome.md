# ADR-0013 — Temps sensible (pictogramme) dérivé des champs AROME

## Statut

Accepté — 2026-06-05. Application de [ADR-0011](0011-single-runs-api-runs-explicites.md)
(question Q1, cohérence des modèles) ; rendu possible par
[ADR-0012](0012-licence-gpl.md) (licence GPL).

## Contexte

Bug observé le 2026-06-05 (Veille du matin) : pour **vendredi après-midi**, le
pictogramme annonçait de la **pluie/bruine** alors que le cumul **et** la
probabilité affichés valaient **0**.

Diagnostic (sur le run 00Z, vérifié) :

- AROME France HD ne fournit **aucun** `weather_code` (0/72 h) ni
  `cloud_cover` total sur l'API *Single Runs* d'Open-Meteo.
- La fusion App 1 (priorité AROME → ARPEGE) comblait donc le `weather_code`
  manquant avec celui d'**ARPEGE**, tandis que la **précipitation** restait
  celle d'**AROME**. Sur la ligne de 15 h : `weather_code = 51` (bruine,
  ARPEGE) collé à `precipitation = 0.0` (AROME).
- La probabilité, elle, vient d'un **troisième** modèle (ensemble ECMWF) → 0 %.

Trois modèles différents affichés comme cohérents : le picto (ARPEGE)
contredit le cumul (AROME). Le découplage `weather_code` / `precipitation` est
**systématique** (AROME ne donne jamais le code), pas un cas isolé.

## Décision

**Fabriquer le code temps depuis les champs AROME eux-mêmes**, pour qu'il soit
cohérent avec le cumul AROME par construction.

Méthode : **porter l'algorithme de symbole de MET Norway**
(`metno/weather_symbol`, GPL) plutôt qu'inventer des seuils. C'est une
méthodologie **ouverte, lisible et opérée par un service météo national**.
L'**ECMWF** ne publie **aucun** algorithme réutilisable (ses météogrammes sont
des box-plots) — donc « suivre l'ECMWF » n'était pas possible.

Implémentation : `src/meteo_socle/indices/temps_sensible.py` (calcul **dans le
socle**, cf. principe de cohérence inter-apps). Le code dérivé est imposé dans
la fusion App 1 là où les champs AROME existent, l'ancien code restant en repli
pour la queue ARPEGE.

Seuils portés fidèlement (vérifiés par les 18 cas de test de MET Norway,
rejoués en Python) :

- **nébulosité** % → 0/1/2/3 aux bornes 13 / 38 / 86 ;
- **précipitation** : paliers interpolés entre 1 h `{0.1, 0.25, 0.95}` et 6 h
  `{0.5, 0.95, 4.95}` mm ;
- **phase** pluie/neige fondue/neige aux bornes 1.5 / 0.5 °C ;
- **averses** (ciel partiel) vs **pluie continue** (ciel couvert) ;
- réduction « nuages hauts » (couvert de cirrus seuls → partiellement nuageux).

Ajouts propres au dépôt (**signalés, provisoires, à valider terrain** — cf.
principe « vérifier les substitutions ») :

- **nébulosité totale** reconstruite des trois couches AROME (recouvrement
  aléatoire `1−(1−bas)(1−moy)(1−haut)`), AROME ne donnant pas le total ;
- **orage** dérivé de la **CAPE** (≥ 200 J/kg + pluie) — MET Norway prend un
  booléen ;
- **brouillard** dérivé de l'**humidité** (≥ 97 %, sans pluie), `visibility`
  étant indisponible ;
- **projection vers OMM 4677** (table de `pictograms.py`) : pluie continue
  61/63/65, averses 80/81/82, neige 71/73/75, averses de neige 85/86 ; la
  neige fondue (sans icône OMM) est rendue comme neige ; l'orage par 95 sans
  distinction d'intensité.

## Conséquences

- Variables AROME ajoutées au fetch : `cloud_cover_low/mid/high`, `cape`.
- Picto Veille cohérent avec le cumul (cas vendredi : « Couvert », plus de
  bruine fantôme).
- **Forme découplée du fond** : le vocabulaire de sortie reste OMM 4677, donc
  le choix du jeu d'icônes reste indépendant. Choix retenu (2026-06-05) :
  bascule de Meteocons (MIT) vers les **icônes MET Norway / yr** (MIT,
  `assets/yr/`) — même service météo national pour le fond et la forme.
- **App 2** non modifiée : ses séries mono-modèle (ARPEGE/ECMWF) fournissent
  leur propre `weather_code`, cohérent avec leur propre pluie. L'unification du
  calcul via le socle reste un suivi possible (cohérence de méthode).
- Seuils orage/brouillard à confronter à la doctrine terrain avant de leur
  faire confiance.

## Alternatives écartées

- **Garder le `weather_code` ARPEGE** : la cause même du bug.
- **Récupérer le symbole déjà calculé par MET Norway** (modèle metno sur
  Open-Meteo) : calculé sur *leur* modèle, pas AROME → réintroduit l'incohérence
  avec le cumul AROME.
- **Inventer nos propres seuils** : moins bien sourcé qu'un service national.
- **API Météo-France directe** : MF ne publie pas d'algorithme code-temps
  (symbole « temps sensible » propriétaire). Plus lourd, sans gain.
