# ADR-0004 — Modèle ETP : FAO Penman-Monteith horaire

## Statut

Accepté — 2026-05-28

## Contexte

L'évapotranspiration potentielle de référence (ETP) est l'indicateur agronomique central de plusieurs sorties du socle :

- entrée du **bilan hydrique** culture-spécifique (avec coefficient cultural Kc),
- entrée des **fenêtres d'irrigation** (déficit cumulé P − ETP),
- comparaison croisée pour validation de plausibilité (ETP recalculée vs ETP fournie par MF / Open-Meteo).

Plusieurs formulations existent : Penman 1948 (original), Penman-Monteith 1965, FAO-56 Penman-Monteith (Allen et al. 1998), Hargreaves-Samani 1985 (simplifiée à T° uniquement), Priestley-Taylor 1972 (simplifiée à Rn et T°), Thornthwaite 1948 (très grossière, T° et latitude).

Le code existant `app-bilan-hydrique/etp.py` (Alexis Tantet) implémente déjà **FAO Penman-Monteith en pas horaire**, avec :
- calcul du rayonnement extraterrestre via `pvlib` (R_a, R_so),
- estimation du clearness ratio à partir du rayonnement global mesuré,
- décomposition du rayonnement net en composantes ondes courtes (R_ns) et ondes longues (R_nl),
- flux de chaleur du sol G calculé différemment de jour et de nuit (zenith solaire),
- conversion vent 10 m → 2 m via la fonction logarithmique standard.

Le choix se pose donc surtout entre **confirmer** Penman-Monteith FAO horaire ou **dégrader** à une formulation plus simple si jamais des inputs manquent.

## Décision

Le modèle d'ETP de référence du socle est **FAO Penman-Monteith horaire**, tel que défini dans la publication FAO Irrigation and Drainage Paper No. 56 (Allen et al. 1998), équations 53 à 56 pour le pas horaire.

Référence canonique : **Allen, R.G., Pereira, L.S., Raes, D., Smith, M., 1998.** *Crop Evapotranspiration — Guidelines for Computing Crop Water Requirements*. FAO Irrigation and Drainage Paper 56, Rome. Disponible : <https://www.fao.org/4/X0490E/x0490e00.htm>.

Inputs nécessaires (horaires) :

| Symbole | Variable | Unité | Source |
|---|---|---|---|
| T | Température 2 m | °C ou K | observation ou prévision |
| RH | Humidité relative | fraction 0-1 | observation ou prévision |
| u₁₀ | Vitesse vent 10 m | m/s | observation ou prévision |
| R_s | Rayonnement global incident | W/m² ou MJ/m²/h | observation ou prévision |
| φ, λ, z | Latitude, longitude, altitude | ° et m | paramètre du site |

Le code de calcul est migré depuis `app-bilan-hydrique/etp.py` selon la procédure de l'ADR-0003.

## Justification

- **Référence FAO** : standard international le plus largement utilisé pour l'irrigation, accepté par OMM, FAO, INRAE. Cite-able dans tout document scientifique.
- **Pas horaire** : la version FAO horaire (eq. 53-56) capte mieux les ETP en climat océanique où la journée alterne nuages et soleil — la version quotidienne (eq. 6) lisse trop ces variations.
- **Inputs disponibles** : les cinq variables nécessaires sont fournies par toutes les sources retenues (cf. ADR-0002 mapping besoin × source).
- **Code existant** : déjà implémenté et validé en usage. Migration par characterization testing (cf. ADR-0003).

## Conséquences

- **Dépendance `pvlib`** conservée pour le rayonnement extraterrestre et le calcul de position solaire. Bibliothèque scientifique mature et maintenue (NREL).
- **Robustesse au rayonnement manquant** : si une station MF n'a pas le rayonnement global, le calcul d'ETP nécessite un fallback. Stratégie traitée en ADR-0006 (stratégie de couverture rayonnement).
- **Validation croisée** : SAFRAN et Open-Meteo fournissent une ETP déjà calculée par leurs auteurs. Le test de cohérence "ETP socle vs ETP fournisseur" est intégré comme test d'intégration (écart attendu < 10 % en climat océanique tempéré, à vérifier empiriquement).
- **Pas de Hargreaves-Samani ni autre dégradation** en v0. Si un site futur ne dispose pas de tous les inputs, la décision sera reprise en ADR successeur — pas en bricolage silencieux.
- **Limites assumées** : Penman-Monteith FAO suppose une référence "gazon court bien irrigué" comme couvert standard. L'ETP réelle de chaque culture nécessite l'application du coefficient cultural Kc (cf. bilan hydrique, valeurs ARDEPI maraîchage).

## Références complémentaires

- Allen et al. 1998, FAO Bulletin 56 (référence principale).
- Penman, H.L., 1948. *Natural evaporation from open water, bare soil and grass*. Proc. R. Soc. Lond. A 193, 120–145.
- Monteith, J.L., 1965. *Evaporation and environment*. In: The State and Movement of Water in Living Organisms, Symp. Soc. Exp. Biol. 19, 205–234.
- ARDEPI, *Estimer ses besoins en eau — Maraîchage*. <https://www.ardepi.fr/nos-services/vous-etes-irrigant/estimer-ses-besoins-en-eau/maraichage/>
