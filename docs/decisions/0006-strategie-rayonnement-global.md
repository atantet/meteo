# ADR-0006 — Stratégie de couverture du rayonnement global incident (R_s)

## Statut

Accepté — 2026-05-28
*Révision majeure intégrant l'investigation empirique de la couverture rayonnement Météo-France autour de Pleine-Fougères.*

## Contexte

Le **rayonnement global incident R_s** est l'input le plus contraint du calcul ETP FAO Penman-Monteith (cf. ADR-0004) et de la correction radiative du modèle d'humectation foliaire Magarey (cf. ADR-0005).

Problème : **toutes les stations Météo-France ne mesurent pas le rayonnement**. Le réseau RADOME a environ 80 stations principales équipées sur ~150 stations principales. Selon les stations équipées présentes autour de Pleine-Fougères, le R_s observé est de meilleure ou moins bonne qualité spatiale.

Pour la prévision et la climatologie SAFRAN, le R_s est modélisé / ré-analysé et disponible partout — la contrainte se concentre sur l'**observation horaire temps réel**.

Cet ADR est l'**application au cas spécifique du R_s** du principe transverse **n°7 d'agrégation multi-station** — mais il acte explicitement une **exception** justifiée par les données empiriques ci-dessous.

## Investigation empirique de la couverture (réalisée 2026-05-28)

Données issues du dépôt antérieur `app-bilan-hydrique` (sélection nn=9 et nn=14 sur DPClim horaire et DPPaquetObs pour le site La Petite Claye, Pleine-Fougères) :

### Les 14 stations Météo-France les plus proches

| dist_km | ID | Nom | typePoste DPClim | équipée R_s |
|---:|---|---|---:|---|
| ~10 | 50410003 | PONTORSON | 1 | **non** (vérifié) |
| ~20 | 35110003 | FEINS_SA | 1 | **non** (vérifié) |
| ~30 | 35162003 | LOUVIGNE-DU-DESERT | 1 | non (typePoste 1) |
| ~40 | 35228001 | **DINARD** | **0** | **OUI** (vérifié) |
| ... | (9 autres en 35/50, toutes typePoste 1 ou 2) | | | non |

### Élargissement nécessaire pour atteindre N≥2 équipées

| dist_km | ID | Nom | typePoste | équipée R_s |
|---:|---|---|---:|---|
| ~50 | 35281001 | RENNES-ST JACQUES | 0 | **probable** (typePoste 0, non vérifié faute de données) |
| ~96 | 22372001 | ST BRIEUC | 0 | **probable** (typePoste 0, non vérifié) |
| ~144 | 22113006 | LANNION_AERO | 0 | probable |
| ~146 | 22168001 | PLOUMANAC'H | 0 | probable |

**Constat structurel** : dans un rayon de 50 km autour de Pleine-Fougères, **DINARD est la seule station MF confirmée équipée R_s**. Le principe transverse n°7 d'agrégation multi-station ne peut donc pas s'appliquer en l'état pour le R_s, à la différence des autres variables d'observation (T°, HR, vent, pluie) pour lesquelles 9 stations sont disponibles dans 30 km.

## Décision

Deux régimes distincts dans le socle, l'un standard, l'autre spécifique au R_s.

### Régime standard (T°, HR, vent, pluie, point de rosée)

Application directe du principe n°7 : agrégation **inverse-distance²** sur N=3 à 5 stations Météo-France les plus proches dans un rayon ~50 km. Le `liste_stations_DPClim_horaire_*.csv` filtré par disponibilité de la variable donne le sous-ensemble exploitable.

### Régime spécifique R_s — exception assumée au principe n°7

Faute de couverture multi-station possible dans un rayon utile pour le rayonnement, le R_s d'observation utilise une **cascade hybride observation+modèle** en deux niveaux.

**Niveau 1 — Hybride DINARD + Open-Meteo modélisé** *(mode standard)*

R_s = combinaison pondérée de deux mesures indépendantes :

- *Observation locale* : **DINARD** (ID 35228001, lat 48.585, lon -2.076, alt 65 m, typePoste 0, à ~40 km au NO).
- *Modèle re-analysé* : **Open-Meteo** R_s modélisé au centroïde Pleine-Fougères (distance "0" puisque interpolé au point cible).

Pondération initiale par défaut : 50/50 en l'absence de calibration empirique. À reprendre une fois qu'un historique permet d'estimer le biais relatif des deux sources.

**Niveau 2 — Open-Meteo seul** *(fallback si DINARD indisponible)*

Si DINARD est en panne ou ses données manquent : R_s = Open-Meteo modélisé seul. État signalé `qualite: degraded` dans les métadonnées.

**Niveau 2 bis — Modèle clearness × cloud_cover** *(fallback ultime si Open-Meteo R_s indisponible)*

R_s ≈ R_so × clearness(couverture_nuageuse)

où R_so est le rayonnement global pour ciel clair (calculé via `pvlib`, déjà dans `etp.py` migré), et clearness est dérivé de cloud_cover via une relation publiée à choisir (Black 1956, Kasten & Czeplak 1980). État signalé `qualite: modeled`.

### Évolution v1+ — élargir vers N=2-3 sur observation pure

Une fois le projet en route, vérifier (via un appel DPClim sur 2024) si **RENNES-ST JACQUES** (~50 km, typePoste 0) et **ST BRIEUC** (~96 km, typePoste 0) sont équipées R_s. Si confirmées, le Niveau 1 peut évoluer vers une vraie agrégation inverse-distance² N=2 ou N=3 (DINARD + RENNES, +/- ST BRIEUC), avec Open-Meteo rétrogradé en validation croisée plutôt qu'en mesure agrégée.

## Justification de l'exception au principe n°7

- **Réalité empirique d'abord** : la couverture rayonnement RADOME en Bretagne nord ne permet pas l'agrégation multi-station dans un rayon où la représentativité locale reste défendable.
- **Pas de mensonge par omission** : l'exception est documentée, son périmètre est explicite (R_s uniquement), et le principe n°7 reste actif sur toutes les autres variables.
- **Mix observation + modèle** : combiner DINARD (observation locale, 40 km) et Open-Meteo (modèle au point cible) reste un mécanisme d'agrégation au sens large — deux sources indépendantes confrontées, ce qui satisfait l'esprit du principe n°7 même si la lettre (multi-station) ne tient pas.
- **Réversibilité** : si l'évolution v1 confirme RENNES et ST BRIEUC équipées, on revient à une stricte agrégation multi-station observée et l'exception disparaît.

## Conséquences

- **Métadonnées obligatoires** : chaque jeu R_s produit porte `source_niveau` (1 hybride / 2 OM seul / 2bis modèle clearness), `sources_utilisees` (liste), `poids` (liste), `qualite` (normal / degraded / modeled).
- **Affichage utilisateur** : tout indicateur en aval (ETP, mildiou via humectation) affiche ces métadonnées dans son expand "vérifier la source", avec la mention explicite "exception R_s — voir ADR-0006".
- **Tests d'intégration** : comparaison croisée DINARD vs Open-Meteo R_s sur 12 mois → calibration du biais relatif, ajustement éventuel de la pondération initiale 50/50.
- **Tâche de vérification équipement** : appel DPClim sur 2024 pour 35281001 (RENNES) et 22372001 (ST BRIEUC), vérifier présence de GLO non vide. À programmer dès que le socle a accès au token MF.

## Référence aux données ayant alimenté cet ADR

Sélections nn=9 et nn=14 de l'utilisateur dans `~/Documents/Travail/1_agri/Technique/app-bilan-hydrique/data/{DPClim,DPPaquetObs}/donnees_*_lapetiteclaye_*_stations.csv` (consultées 2026-05-28). Listes complètes des stations par département dans le même répertoire `liste_stations_DPClim_horaire_{22,35,50}.csv`. Ces fichiers ne sont pas versionnés dans le présent dépôt (cf. ADR-0001 — données opérationnelles ignorées) mais leur traitement est reproductible via le code à migrer.

## Références bibliographiques

- Allen, R.G., Pereira, L.S., Raes, D., Smith, M., 1998. *Crop Evapotranspiration*. FAO Bulletin 56, équations 21-26 pour R_so et la correction de clearness.
- Kasten, F., Czeplak, G., 1980. *Solar and terrestrial radiation dependent on the amount and type of cloud*. **Solar Energy** 24, 177-189.
- Black, J.N., 1956. *The distribution of solar radiation over the Earth's surface*. **Arch. Meteorol. Geophys. Bioklimatol.** B 7, 165-189.
