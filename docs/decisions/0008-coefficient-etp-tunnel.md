# ADR-0008 — Coefficient de réduction ET₀ sous tunnel froid

## Statut

Accepté — 2026-05-29
*Note : valeur par défaut 0.70 issue de la médiane de la littérature
tempérée. Recalibration locale prévue après une saison d'observations
(évaporimètre tunnel ou suivi RU sol).*

## Contexte

L'App 2 Op expose un **bilan hydrique sous tunnel** (cf. choix
utilisateur 2026-05-29 : modèle sol complet via
`meteo_socle.indices.bilan_hydrique.calcul_bilan`). Pour ce bilan, il
faut une **ET₀ représentative de l'intérieur du tunnel**, différente
de l'ET₀ FAO Penman-Monteith calculée sur les conditions extérieures
par le socle (cf. ADR-0004).

L'ET₀ intérieure est généralement **plus basse** que l'ET₀ extérieure
parce que :

- Le film polyéthylène **filtre** 10-15 % du rayonnement global (PAR
  et infrarouge proche).
- Le **vent est cassé** (résistance aérodynamique × 5-10 dans
  l'équation Penman-Monteith — Stanghellini 1987).
- L'**humidité relative est plus haute** (transpiration cumulée + air
  confiné), ce qui diminue le gradient de vapeur (deuxième terme de
  Penman-Monteith).
- La **T° d'air est généralement plus haute** le jour (effet de
  serre), partiellement compensatoire — mais l'effet net reste une
  ET₀ intérieure réduite.

**Contraintes du projet** :

- Pas de capteur intérieur (T°/HR/anémomètre tunnel) à La Petite Claye.
- Calcul accessible à partir des seules variables Open-Meteo extérieures
  (cf. principes #2 simplicité et #6 pas de boîte noire).
- Aucun modèle de référence FR open-source pour la transposition
  tunnel-froid (Mileos / Milsol traitent autre chose).
- Rigueur scientifique (principe #5 transparence) : la méthode doit
  être citable et auditable.

Trois familles d'approches examinées :

| Méthode | Référence | Inputs | Précision | Adapté ? |
|---|---|---|---|---|
| Coefficient fixe | Castilla 2013 ch. 4 ; Möller et al. 2009 | ET₀_ext × k | ±15-25 % | Oui — simple, lisible |
| Penman-Monteith adapté | Stanghellini 1987 ; Möller 2009 | T°/HR/vent intérieurs | ±10 % | Non en v0 (besoin capteurs) |
| Capteur évapomètre | hardware direct | mesure directe | ±5 % | Non en v0 (pas d'instrumentation) |

## Décision

Le socle expose un **coefficient ET tunnel fixe**, paramétrable par
l'utilisateur via slider App 2 Op (range 0.40-1.00), avec **valeur par
défaut 0.70**.

> ET₀_tunnel = k_tunnel × ET₀_extérieur(FAO Penman-Monteith socle)

### Plage par défaut et signification opérationnelle

| Configuration tunnel | k_tunnel typique |
|---|---|
| Tunnel ouvert (portes constamment ouvertes, équivalent abri pluie) | 0.85-0.95 |
| **Tunnel froid standard (ventilation latérale jour, portes fermées nuit)** | **0.65-0.75 — défaut 0.70** |
| Tunnel froid bien fermé (ventilation minimale) | 0.50-0.65 |
| Serre fermée chauffée | hors périmètre v0 |

### Indépendance du choix Kc culture

Le coefficient k_tunnel agit **uniquement sur l'ET₀**, pas sur le Kc
culture. La chaîne en v0 est donc :

> ET_c_tunnel = Kc(culture, stade) × k_tunnel × ET₀_extérieur

Le Kc utilisé reste celui ARDEPI plein champ (cf. ADR-0007 contexte
mildiou pour la justification du choix ARDEPI comme référence). Un Kc
dédié serre/tunnel n'est pas disponible en open data ; cette
approximation sera documentée en clair dans l'app.

## Justification

- **Coefficient fixe en première intention** : (i) zéro input
  supplémentaire requis ; (ii) lisibilité totale du calcul (principes
  #5 et #6) ; (iii) littérature publiée donne directement la plage
  pertinente ; (iv) la précision ±15-25 % est largement acceptable
  pour un indicateur informationnel (principe #1 accompagner pas
  prescrire) — le maraîcher conserve sa décision finale d'irrigation.
- **Pas de Penman-Monteith intérieur en v0** : nécessite des mesures
  T°/HR/vent intérieures qu'on n'a pas, et même Stanghellini 1987
  noter que la calibration site-spécifique est nécessaire pour passer
  sous les ±10 %.
- **Pas de capteur en v0** : décision matérielle séparée, à arbitrer
  après une saison d'usage. Si la conviction utilisateur que le bilan
  diverge de la réalité observée, on instrumentera.
- **Slider plutôt que valeur fixe enfouie** : (i) permet à l'utilisateur
  de simuler `k = 0.60` vs `0.80` et de juger lui-même de la sensibilité
  (principe #5) ; (ii) prépare la recalibration locale en exposant
  directement le levier.

## Conséquences

- **Précision attendue : ±15-25 %** sur le besoin d'irrigation
  cumulé 7 j sous tunnel. À documenter clairement dans l'app.
- **Identique pour toutes les cultures** : la même valeur k_tunnel est
  appliquée à Tomate, Aubergine, Poivron, Concombre, etc. Pas de
  différenciation par hauteur de culture ou par densité de feuillage,
  car le coefficient agit sur ET₀ (climat) pas ET_c (culture). Si la
  réalité montre des écarts marqués entre cultures, prévoir un ADR
  successeur avec k_tunnel × culture.
- **Sensibilité saisonnière non modélisée** : k_tunnel devrait varier
  saisonnièrement (plus bas l'été quand les portes restent ouvertes
  jour et nuit ; plus haut l'hiver quand le tunnel est fermé). En v0
  on accepte cette approximation ; documenter l'écart si observation
  montre un biais saisonnier.
- **Validation locale post-saison N+1** : protocole minimal — relever
  la consommation d'eau effective au compteur, comparer au besoin
  prédit par l'app, ajuster `k_tunnel` pour recaler. À documenter
  dans un futur ADR si modification structurante.
- **Aucun coût calcul** : multiplication scalaire dans la fonction
  `bilan_tunnel_carry_over` de `apps/operationnelle/charts.py`.

## Références

- **Castilla, N., 2013.** *Greenhouse Technology and Management*,
  2nd ed., CABI, Wallingford, UK. Chapitre 4 "Crop water requirements"
  pour la plage de k_tunnel selon ventilation et type d'abri.
- **Möller, M., Tanny, J., Cohen, S., Assouline, S., 2009.**
  *Estimating the aerodynamic resistance of a screen-house using
  artificial neural networks*. **Agricultural and Forest Meteorology**
  149, 358-364. Justifie quantitativement la réduction de vent dans
  l'équation Penman-Monteith en abri.
- **Stanghellini, C., 1987.** *Transpiration of greenhouse crops — an
  aid to climate management*. Thesis, Wageningen Agricultural
  University. Référence canonique pour Penman-Monteith adapté serre.
- **Möller, M., Stanghellini, C., 2017.** *Climate effects on
  greenhouse crops*. Dans *Achieving sustainable greenhouse cultivation*,
  Burleigh Dodds. Synthèse moderne incluant tunnels froids.
- **Allen, R.G. et al., 1998.** *Crop Evapotranspiration*. FAO 56.
  Référence ET₀ extérieur (cf. ADR-0004).
- **ARDEPI**, *Estimer ses besoins en eau — Maraîchage*. Source Kc
  utilisée en aval, calibrée plein champ Provence (cf. ADR-0007 §
  contexte).
