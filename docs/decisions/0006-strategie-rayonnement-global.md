# ADR-0006 — Stratégie de couverture du rayonnement global incident (R_s)

## Statut

Accepté — 2026-05-28
*Note : l'identification concrète des stations MF équipées rayonnement autour de Pleine-Fougères est en cours d'investigation (cf. § "Investigation à mener" ci-dessous).*

## Contexte

Le **rayonnement global incident R_s** est l'input le plus contraint du calcul ETP FAO Penman-Monteith (cf. ADR-0004) et de la correction radiative du modèle d'humectation foliaire Magarey (cf. ADR-0005).

Problème : **toutes les stations Météo-France ne mesurent pas le rayonnement**. Le réseau RADOME a environ 80 stations principales équipées sur ~150 stations principales. Selon les stations équipées présentes autour de Pleine-Fougères (35), le R_s observé sera de meilleure ou moins bonne qualité spatiale.

Pour la prévision et la climatologie SAFRAN, le R_s est modélisé / ré-analysé et disponible partout — la contrainte se concentre sur l'**observation horaire temps réel**.

Cet ADR est l'**application au cas spécifique du R_s** du principe transverse **n°7 d'agrégation multi-station** (cf. principes de conception du projet). Aucune mesure n'étant prise directement à Pleine-Fougères, toute valeur d'observation R_s doit résulter d'une agrégation de stations distantes, et non d'une lecture mono-station, même si la station unique est proche.

## Décision

Une **cascade en deux niveaux** est implémentée, du mode standard (agrégation multi-station) au fallback dégradé (modèle ciel clair × couverture nuageuse).

### Niveau 1 — Agrégation multi-station inverse-distance² (mode standard)

Pour l'observation temps réel et l'historique consolidé : interpolation **inverse-distance²** (déjà implémentée dans `geo.py`) sur les **N stations Météo-France équipées rayonnement** les plus proches.

Paramètres par défaut, conformes au principe n°7 :

- **N = 3 à 5 stations** (compromis statistique vs représentativité locale).
- **Distance maximale considérée : ~50 km** (à calibrer empiriquement après identification des stations équipées en Bretagne nord et Normandie ouest).
- Si **moins de 3 stations équipées** sont disponibles dans le rayon maximum, N est réduit en conséquence — état signalé dans les métadonnées (`qualite: degraded`).
- Si **plus de 5 stations équipées** sont disponibles, on conserve les 5 plus proches (pas d'amélioration marginale au-delà — sur-pondération des stations lointaines au détriment du signal local).

Les métadonnées de sortie incluent : nombre de stations utilisées, identifiants, distances individuelles, distance moyenne pondérée, qualité d'interpolation.

Implémentation : extension du `meteofrance.py` migré pour filtrer le `liste-stations` sur l'attribut "équipée rayonnement" (à vérifier dans la doc API), sélection des N plus proches par distance haversine via `geo.py`, agrégation inverse-distance².

### Niveau 2 — Modèle clearness × couverture nuageuse (fallback dégradé, si N=0)

Si **aucune station équipée n'est disponible** dans le rayon maximum, ou si toutes les stations équipées sont en panne ce jour-là :

R_s ≈ R_so × clearness(couverture_nuageuse)

où R_so est le rayonnement global pour ciel clair (calculé via `pvlib`, déjà disponible dans `etp.py` migré), et le clearness ratio est dérivé de la couverture nuageuse (Open-Meteo fournit `cloud_cover` modélisée partout) via une relation publiée à choisir (Black 1956, Kasten & Czeplak 1980 typiquement).

Les sorties produites par ce niveau sont **explicitement étiquetées "modélisées"** dans les métadonnées et le rendu utilisateur (icône / mention "R_s modélisé, stations équipées indisponibles").

## Justification

- **Application du principe n°7** : aucune lecture mono-station, même proche, ne représente fidèlement le R_s à Pleine-Fougères. L'agrégation lisse les biais ponctuels (instrumentation, micro-climat, dérive) et capte mieux la météo locale.
- **Compromis N × distance** : trois stations donnent une statistique minimale (un point ne tient pas un budget d'erreur), cinq saturent le bénéfice de l'agrégation tout en gardant la pertinence locale. Plus de cinq dilue le signal.
- **Pas de mensonge par omission** : un calcul ETP produit avec R_s modélisé (niveau 2) doit être visiblement distingué d'un calcul ETP avec R_s agrégé multi-station (niveau 1). Aligne avec le principe de transparence (n°5).
- **Réutilisation maximale** du code existant : `meteofrance.py` pour le filtrage stations, `geo.py` pour l'agrégation inverse-distance², `etp.py` pour R_so via `pvlib`.
- **Pas de fallback silencieux** : si la cascade dégrade au niveau 2, l'utilisateur le sait.

## Investigation à mener (action ouverte)

L'identification concrète des **stations MF équipées rayonnement dans un rayon utile** autour de Pleine-Fougères (centroïde commune approximatif lat 48.46, lon -1.55) est en cours via un agent de recherche dédié. Candidates probables à vérifier :

- Dinard (~30 km NE)
- Rennes-Saint-Jacques (~45 km S)
- Saint-Brieuc (~70 km O)
- Pleurtuit, Mont-Saint-Michel, Cherrueix : à vérifier équipement
- Caen-Carpiquet (~120 km E)

Le rapport de l'investigation alimentera : (a) la liste opérationnelle des stations agrégées en Niveau 1, (b) la calibration empirique du rayon maximal (50 km par défaut), (c) éventuellement la décision d'élargir le rayon si la couverture rayonnement est sparse.

## Conséquences

- **Métadonnées obligatoires** : chaque jeu de données R_s produit par le socle porte les attributs `source_niveau` (1/2), `stations_utilisees` (liste IDs), `distances_km` (liste), `distance_moyenne_km`, `qualite` (normal / degraded / modeled).
- **Affichage utilisateur** : tout indicateur en aval (ETP, mildiou via humectation) qui dépend de R_s doit pouvoir afficher ces métadonnées dans son expand "vérifier la source".
- **Tests d'intégration** : un test compare R_s niveau 1 vs niveau 2 sur jour ensoleillé / nuageux pour vérifier que la cascade dégrade dans le bon sens (niveau 2 moins précis), et que la cascade dégradée intermédiaire (N=2 puis N=1) ne franchit pas la transition vers modèle silencieusement.
- **Évolution v1+** : intégration possible de **stations Open-Meteo** comme source supplémentaire (modèle de re-analyse 1 h), ou installation d'un **pyranomètre local** (capteur PAR + R_s) à la ferme. Une mesure locale supersède le Niveau 1, mais la cohérence avec l'agrégation reste calculée comme contrôle qualité (cf. principe n°7).
- **Risque** : si moins de 3 stations équipées sont dans un rayon de 50 km, le système fonctionne en mode dégradé (N=1 ou N=2) ou niveau 2 dès le départ. Décision sur ajustement du rayon max à reprendre après investigation.

## Références

- Allen, R.G., Pereira, L.S., Raes, D., Smith, M., 1998. *Crop Evapotranspiration*. FAO Bulletin 56, équations 21-26 pour R_so et la correction de clearness.
- Kasten, F., Czeplak, G., 1980. *Solar and terrestrial radiation dependent on the amount and type of cloud*. **Solar Energy** 24, 177-189.
- Black, J.N., 1956. *The distribution of solar radiation over the Earth's surface*. **Arch. Meteorol. Geophys. Bioklimatol.** B 7, 165-189.
