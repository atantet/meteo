# ADR-0010 — Doctrine pragmatique LWD (rollback Smith vers HR ≥ 90 %)

## Statut

Accepté — 2026-05-29
*Successeur partiel de [ADR-0005](0005-modele-humectation-foliaire.md)
qui prévoyait Magarey DPD/NWP en production. Recadre la doctrine LWD
en mode pragmatique terrain plutôt qu'en mode modèle théorique
absolu.*

## Contexte

L'ADR-0005 prescrivait une cascade Magarey DPD/NWP (production) +
CART Gleason 1994 (contrôle) + HR ≥ 90 % (baseline visuelle). En
2026-05-29, deux essais empiriques ont remis cette doctrine en cause :

1. **CART Gleason 1994** implémenté en attendant le papier Magarey 2005,
   puis utilisé comme input de Smith mildiou (cf. ADR-0007).
   Comparaison sur 30 ans ERA5 Pleine-Fougères a montré une **explosion
   du nombre de périodes Smith** : ~17/an (HR proxy historique) → ~84/an
   (LWD Gleason). Biologiquement implausible — pas 84 jours de risque
   mildiou réel par an sur la côte bretonne.

2. **Diagnostic de la cause** : CART Gleason a une « zone basse »
   *DPD ≤ 3.7 °C → mouillé toujours* qui capture **toutes les nuits
   océaniques** parce que la T° s'aligne sur le point de rosée par
   saturation. Gleason 1994 était calibré **Iowa** (continental sec),
   pas climat océanique humide. Sa transposition Bretagne donne 16 h/jour
   moyennes d'« humectation » — non physiquement crédible.

3. **Magarey 2005 examiné de plus près** : (i) calibration en **chambre
   environnementale contrôlée** (Magarey, Russo, Seem, Gadoury 2005
   *Agric. For. Meteorol.* 128:111-122) — pas validation champ ;
   (ii) inputs lourds (LAI, R_n net, h_transfer, largeur feuille)
   qu'on **ne mesure pas** à La Petite Claye ; (iii) destiné aux
   **systèmes régionaux d'aide à la décision** (downscaling NWP gros
   pixels), pas à une exploitation individuelle.

**Question revisitée** : la chaîne Magarey/Gleason est-elle réellement
adaptée à l'usage maraîcher local ? La réponse pragmatique est non.

## Décision

Le socle revient à **Smith 1956 avec son proxy historique HR ≥ 90 %**
comme indicateur de production unique sur les 3 apps.

### Rôles des modèles LWD dans le socle

| Modèle | Statut v0 | Usage |
|---|---|---|
| HR ≥ 90 % | **Production** | Input de Smith mildiou dans Veille / Op / Climato |
| CART Gleason 1994 | **Inspection visuelle seule** | Colonne `lwd_heures_gleason` dans Op + figure comparative dans Climato. **Pas connecté à Smith.** |
| Magarey DPD/NWP 2005 | **Reporté sine die** | Pas pertinent au scope exploitation individuelle |
| SWEB Magarey 1999 | **Reporté sine die** | Idem |

### Voie v1 réaliste : instrumentation locale

Le vrai progrès ne passe pas par une physique plus fine sur la donnée
maille 25 km, mais par une **donnée locale** :

1. **Sonde T+HR autonome sous abri + extérieur** (~80 € Tinytag/Onset,
   Hobo ou équivalent) + datalogger. À installer printemps N+1.
2. **Saison de relevés** : enregistrer HR + T continu + observations
   visuelles de mouillage matinal sous abri.
3. **Recalibration empirique du seuil HR** par micro-climat : tunnel
   ouvert vs fermé, sol nu vs paillé, à proximité d'une serre vs en
   plein vent. Le seuil 90 % de Smith est un défaut universel UK 1955 ;
   à La Petite Claye il peut être 85 % (tunnel fermé) ou 92 % (tunnel
   très ventilé).
4. **Validation croisée** entre prévision Open-Meteo HR maille 25 km
   et mesure locale sous abri : facteur d'ajustement.

### Rôle conservé de l'ADR-0005

L'ADR-0005 reste valide comme **état de l'art bibliographique LWD**.
Il documente correctement les familles de modèles et les compromis.
Sa **prescription opérationnelle** (Magarey en production) est
remplacée par cet ADR-0010 ; sa **revue de littérature** est conservée
comme référence.

## Justification

- **Smith HR ≥ 90 % a été calibré terrain** sur pomme de terre UK
  (climat océanique tempéré humide, analogue Bretagne). Doctrine
  encore citée par RHS, ADAS, CTIFL. Conséquence numérique : ~17
  périodes Smith / an sur 30 ans ERA5 Pleine-Fougères — cohérent
  avec doctrine empirique maraîchage breton.
- **CART Gleason 1994** : modèle robuste mais **calibré Iowa**. Sans
  ré-étalonnage des seuils DPD pour climat océanique (3.7 °C trop
  haut), donne 5× trop de mouillage. Garde une valeur en
  **diagnostic** mais pas en production.
- **Magarey DPD/NWP** : valeur scientifique réelle pour les agences
  régionales, mais **disproportion** avec la cible "petit maraîchage
  bio diversifié". Calibration chambre + paramètres LAI/R_n pas
  exploitables à l'échelle d'une ferme sans instrumentation. Viole
  le principe #2 *simplicité d'usage et durabilité sans maintenance
  lourde*.
- **Capteur HR local** : voie réaliste, peu coûteuse (~80 €),
  ré-utilisable saison après saison, calibrable. Aligne avec
  principes #1 (accompagner l'empirique) et #2 (durable). C'est la
  **vraie v1** plutôt que la course à la physique de modèle.

## Conséquences

- **Code v0** : retour de la chaîne Smith ← HR ≥ 90 % dans le socle
  (cf. ``meteo_socle.indices.mildiou``). CART Gleason reste dans
  ``meteo_socle.indices.lwd_gleason`` mais n'est plus utilisé comme
  input de Smith — uniquement comme indicateur d'inspection séparé
  dans App 2 Op et figure comparative climato.
- **Configs YAML** : retour du paramètre ``hr_seuil`` (défaut 0.90)
  dans les trois apps (veille, op, climato).
- **Mail Veille / Op UI** : libellés "h HR ≥ 90 %" restaurés.
  Critère pied-de-page mentionne Smith historique.
- **ADR-0005 et ADR-0007** : annoter une note de successeur pointant
  vers cet ADR-0010 pour la doctrine effective.
- **v1 — feuille de route** :
  - 2026 hiver-printemps : choisir + acheter sonde T+HR autonome.
  - Saison 2027 : installer en avril, enregistrer continu, relever
    observations visuelles 6h-8h matin sur 4-6 semaines mai-juin.
  - Automne 2027 : ré-étalonner seuil HR par contexte (tunnel
    ouvert / fermé) en comparant heures HR≥seuil au nb réel d'épisodes
    de rosée observés. Documenter dans futur ADR.
- **Surveillance bibliographique** : si un modèle LWD plus simple et
  calibré climat océanique humide apparaît (post-2026 INRAE /
  CTIFL — *Decid'Herbe*, *OptiProtect*, etc.), l'évaluer comme
  successeur potentiel de HR ≥ 90 %.

## Références

- **Smith, L.P., 1956.** *Potato blight forecasting by 90 per cent
  humidity criteria*. Plant Pathology 5, 83-87. La source —
  toujours d'actualité en doctrine UK / NW Europe.
- **Sentelhas, P.C., Dalla Marta, A., Orlandini, S., Santos, E.A.,
  Gillespie, T.J., Gleason, M.L., 2008.** *Suitability of relative
  humidity as an estimator of leaf wetness duration*. Agric. For.
  Meteorol. 148, 392-400. Quantifie le biais HR ≥ 90 % vs LWD réel
  (1-3 h/jour surestimation). Confirme HR proxy reste utilisable
  avec biais connu.
- **Rowlandson, T., Gleason, M., Sentelhas, P., Gillespie, T., Thomas,
  C., Hornbuckle, B., 2015.** *Reconsidering leaf wetness duration
  determination for plant disease management*. Plant Disease 99,
  310-319. Synthèse récente, conclut que la quête du modèle LWD
  "parfait" est moins importante que l'usage adapté au contexte.
- **Magarey 2005 chapitre review** (Magarey, Seem, Weiss, Gillespie,
  Huber, *Estimating Surface Wetness on Plants*, Agronomy Monograph
  47 ch. 10) : revue méthodologique. Reconnaît explicitement la
  difficulté de calibration site-spécifique des modèles physiques.
- Cf. [ADR-0005](0005-modele-humectation-foliaire.md) pour la revue
  bibliographique LWD complète et les références primaires Gleason
  1994 + Magarey 1999/2005.
