# ADR-0009 — Périmètre du module pépinière v0

## Statut

Accepté — 2026-05-29
*Note : v0 minimaliste centré sur le calendrier semis. Indicateurs
substrat reportés à v1 faute de modèles référencés et calibrés pour
godets en climat tempéré océanique.*

## Contexte

La Petite Claye produit ses propres plants en pépinière interne
(maraîchage bio diversifié, cf. mémoire projet). C'est l'un des
quatre enjeux prioritaires nommés en cadrage initial, mais aucune
feature dédiée n'avait été livrée jusqu'à présent dans aucune des
trois apps.

**Spécificités pépinière vs plein champ** identifiées au cadrage :

| Aspect | Pépinière (godets/mottes) | Plein champ |
|---|---|---|
| Volume substrat | 8-80 ml par godet — RU minuscule | RU du sol racinaire (~30 cm) |
| Dessèchement | Heures (godet plein soleil) | Jours |
| Sensibilité gel | Très forte (plants jeunes gèlent dès +2 °C) | Variable selon culture/stade |
| Sensibilité canicule | Choc thermique sous tunnel > 35 °C | Pression, mais marges |
| Maladies | Pythium fonte semis, Botrytis, Sclerotinia | Mildiou, oïdium, etc. |
| Arrosage | Très fréquent (2-3×/jour été) | Hebdo à quotidien |
| Coefficients culturaux | Pas de Kc ARDEPI pour godets | Kc ARDEPI plein champ disponible |

**Contraintes du projet** :

- Pas de capteurs substrat (sondes humidité, T° substrat) en v0.
- Pas de modèles fonte de semis publics référencés et calibrés pour
  godets en climat océanique tempéré.
- Pas de catalogue Kc godets / motte mottée open source connu.
- Cohérence avec les principes du projet : informationnel non
  prescriptif, transparent, scientifiquement traçable.

## Décision

Le module pépinière v0 livre **uniquement le calendrier semis
recommandé**, qui est l'indicateur le plus actionnable et le mieux
calibré scientifiquement à partir des seules données accessibles
(climato dates de gel) + littérature publiée sur durées d'élevage.

### Périmètre v0 livré

1. **Catalogue durées d'élevage** par culture maraîchère (semis →
   plant prêt à repiquer) — en jours, référencé GRAB / CTIFL / ITAB
   selon les sources publiques. Versionné en JSON dans
   `src/meteo_socle/indices/pepiniere_cycles.json`.

2. **Fonction `date_semis_recommandee(culture, date_plantation_cible,
   marge_securite_j)`** dans `src/meteo_socle/indices/pepiniere.py` :
   calcule la date de semis à partir de la date cible de plantation.

3. **Section App 3 Climato** *Calendrier semis recommandé* :
   - Pour chaque culture courante, fenêtre de plantation cible basée
     sur le 90ᵉ percentile du dernier gel printanier (climato
     1991-2020 — cf. fig-gel-distribution).
   - Date de semis cible déduite : `cible_plantation − durée_élevage`.
   - Tableau récapitulatif culture × date semis × date plantation.

### Hors périmètre v0 (reportés discussions)

Les pistes suivantes ont été explicitement exclues de la v0 par
manque de données locales calibrées ou de modèles référencés simples
et auditables :

- **Indicateur stress hydrique substrat** : nécessiterait un Kc godet
  calibré ou un modèle de RU substrat ; pas trouvé en open source. Une
  approche heuristique (`besoin = facteur × ET₀ × volume_godet`) est
  envisageable mais non publiée → viole le principe #4 rigueur
  scientifique en v0.
- **Risque fonte des semis (Pythium)** : modèles publiés (Erwin &
  Ribeiro 1996, Owen-Going et al. 2008) demandent des inputs substrat
  (T° substrat, EC, saturation) qu'on n'a pas en v0.
- **Risque Botrytis pépinière** : modèles sur HR ambiante + T° (Strömer
  et Pscheidt 2017) applicables en principe — à intégrer en v1 si on
  veut un parallèle au Smith mildiou.
- **Alertes T° extrêmes pépinière** : pourrait être un simple jeu de
  seuils dédié dans `config/veille.yaml` (ex. gel à +2 °C au lieu de
  -2 °C, canicule à 28 °C au lieu de 32 °C) qui s'activerait en
  période d'élevage. Reporté pour cadrage avec l'utilisateur sur la
  saisonnalité réelle de la pépinière à La Petite Claye.

## Justification

- **Calendrier semis = plus grand levier décisionnel** : choisir une
  mauvaise date de semis fait perdre des plants entiers, vs une
  alerte arrosage tardif fait juste perdre une journée. ROI
  informationnel le plus élevé.
- **Bien défini scientifiquement** : durée d'élevage = donnée
  agronomique tabulée par culture (CTIFL, GRAB), pas un modèle
  expérimental.
- **S'appuie sur l'existant** : la climato a déjà calculé la
  distribution des dates extrêmes de gel (cf. fig-gel-distribution
  ajoutée 2026-05-29). Le calendrier est une couche au-dessus.
- **Pas de boîte noire** : tout le calcul est `cible - durée` —
  transparent au max, principe #6 préservé.
- **Hors-périmètre transparent** : la décision liste explicitement ce
  qui n'est pas fait et pourquoi (principe #5).

## Conséquences

- **Catalogue durées d'élevage à maintenir manuellement** : ~20
  cultures, ~30 valeurs ; pas de mise à jour automatique nécessaire.
- **Référencement bibliographique partiel** : les durées d'élevage
  varient sensiblement par variété et contexte (substrat, T°
  d'élevage). Un range plutôt qu'une valeur unique serait plus
  honnête. v0 prend la médiane, à raffiner après une saison.
- **Pas d'intégration App 1 Veille** : la décision de semis se prend
  à l'avance (saison), pas chaque matin. Mail Veille ne gagne rien.
- **Pas d'intégration App 2 Op v0** : possible v0.1 si l'utilisateur
  veut une vue rapide "semis cette semaine" ou "semis à préparer".
  À cadrer avec lui.
- **Validation post-saison N+1** : comparer dates semis recommandées
  vs ce que l'utilisateur fait empiriquement → ajuster durées
  d'élevage si écart marqué.

## Références

- **CTIFL**, *Fiches techniques maraîchage*. Référence professionnelle
  française des durées d'élevage et stades phénologiques.
  <https://www.ctifl.fr/>
- **GRAB**, *Fiches culturales maraîchage biologique*.
  <https://www.grab.fr/>
- **ITAB**, *Maraîchage biologique — fiches techniques*.
  <https://www.itab.asso.fr/>
- **Erwin, D.C., Ribeiro, O.K., 1996.** *Phytophthora Diseases
  Worldwide*. APS Press. Contexte général Pythium / Phytophthora —
  pour référence v1.
- **Owen-Going, T.N. et al., 2008.** *Pythium root rot of greenhouse
  pepper: relationship of nutrient solution electrical conductivity
  and inoculum density to disease severity*. **Canadian Journal of
  Plant Pathology** 30, 132-145. Modèle Pythium pour substrat
  contrôlé — référence v1.
- Cf. ADR-0008 § contexte pour la chaîne Kc/ET₀ et la décision de
  garder Kc ARDEPI plein champ même sous tunnel.
