# ADR-0005 — Modèle de durée d'humectation foliaire (LWD)

## Statut

Accepté — 2026-05-28 — **partiellement remplacé par
[ADR-0010](0010-doctrine-pragmatique-lwd.md) le 2026-05-29.**

La revue bibliographique LWD de cet ADR reste valide comme état de
l'art. **La prescription opérationnelle** (Magarey DPD/NWP en
production + CART Gleason en contrôle) **est remplacée** par la
doctrine pragmatique de l'ADR-0010 : Smith ← HR ≥ 90 % en production
v0, Magarey reporté sine die (trop théorique pour l'échelle de
l'exploitation), Gleason conservé comme indicateur d'inspection.

*Note : DOI exacts à confirmer avant signature finale ; références principales reconnues comme piliers de la littérature LWD.*

## Contexte

La **durée d'humectation foliaire** (Leaf Wetness Duration, LWD) est l'input climatique critique des modèles de risque de maladies cryptogamiques en bio (mildiou tomate, mildiou pomme de terre, alternaria, oïdium, botrytis). Elle conditionne la fenêtre d'infection des spores : sans humectation prolongée, pas d'infection ; au-delà d'un seuil cumulé, l'infection est probable.

**Contraintes du projet** :
- Aucun capteur LWD physique n'est disponible sur l'exploitation (pas de wetness sensor type Davis ou équivalent).
- Le modèle doit être calculable à partir de variables horaires météo standard accessibles via Open-Meteo et Météo-France (T° 2 m, HR, vent 10 m, précipitation, rayonnement global, point de rosée déductible).
- Climat océanique tempéré humide breton : HR nocturne fréquemment > 90 % sans humectation effective ; brouillard côtier ; gradients thermiques nuit/jour modérés. Régime piégeux pour les modèles à seuil HR simple.
- Rigueur scientifique exigée (ADR-0004 et principes transverses) : modèle publié, source citée, hypothèses explicites, limites assumées.

Quatre familles de modèles candidats ont été examinées (rapport bibliographique cité ci-dessous) :

| Famille | Référence | Inputs | Performance climat océanique |
|---|---|---|---|
| Seuil HR (NHRH) | Sutton et al. 1984 ; Rao et al. 1998 | HR | Surestime LWD de 1-3 h/jour (Sentelhas 2008) |
| CART | Gleason et al. 1994 | T, HR, Td, vent, h depuis pluie | Sous-estime LWD en régime advectif humide (calibré Midwest US) |
| DPD/NWP | Magarey et al. 2005 | T, Td, vent, (Rn estimé) | Le plus robuste en climat humide ; calibré sur sorties NWP |
| Bilan énergétique complet | Pedro & Gillespie 1982 ; P-M inversé | T, HR, Td, vent, Rn, albédo, LAI | Précis si Rn fiable ; surdimensionné pour Open-Meteo (GHI seul) |

Le climat océanique tempéré humide est précisément le régime où le seuil HR simple est trompeur (HR ≥ 90 % la nuit sans condensation effective).

## Décision

Le socle implémente la cascade suivante.

### Modèle de production (première intention) — Magarey DPD/NWP (2005)

Algorithme : la feuille est humectée à l'heure *t* si

```
DPD(t) = T(t) − Td(t) < seuil(u(t), R_n(t))
```

où DPD est la *dew point depression*, et le seuil dépend du vent (qui assèche la feuille) et du rayonnement net (qui chauffe la feuille). Implémentation Python en formules fermées (~30 lignes incluant le calcul de Td via Magnus-Tetens et l'estimation de R_n à partir de R_s par FAO-56).

Référence : **Magarey, R.D., Russo, J.M., Seem, R.C., Gadoury, D.M., 2005.** *Surface wetness duration under controlled environmental conditions*. **Agricultural and Forest Meteorology** 128, 111-122. DOI: 10.1016/j.agrformet.2004.10.001 *[à vérifier]*.

### Contrôle croisé — CART Gleason (1994)

Arbre de décision binaire publié, basé sur quatre prédicteurs (T − Td, vent, HR, h depuis pluie). Lancé en parallèle de Magarey pour identifier les heures de désaccord. En cas de divergence > X heures sur une fenêtre journalière, l'heure est étiquetée "ambiguë" dans le module veille (et le calcul mildiou aval annoté en conséquence).

Référence : **Gleason, M.L., Taylor, S.E., Loughin, T.M., Koehler, K.J., 1994.** *Development and validation of an empirical model to estimate the duration of dew periods*. **Plant Disease** 78, 1011-1016 *[DOI à vérifier — APS Press]*.

### Baseline diagnostique — NHRH 90 %

Le seuil HR ≥ 90 % est calculé et **affiché dans les graphiques de diagnostic** comme baseline visuelle, **jamais utilisé en production**. Permet à l'utilisateur de comparer la sortie modèle vs le proxy naïf qu'il aurait pu calculer mentalement.

## Justification

- **Magarey en première intention** : (i) calibré explicitement sur sorties de modèles numériques de prévision, donc cohérent avec Open-Meteo et AROME (cf. ADR-0002) ; (ii) intègre vent et rayonnement, discriminants critiques en climat océanique où la HR seule est trompeuse ; (iii) implémentation triviale en Python par formules fermées.
- **CART Gleason en contrôle** : modèle indépendant (statistique vs physique), permet de signaler les heures ambiguës plutôt que de masquer l'incertitude.
- **NHRH comme baseline visuelle** : alignement avec le principe de transparence (ADR-0001 / principes structurants) — l'utilisateur peut juger par lui-même la valeur ajoutée du modèle.

## Conséquences

- **Pas de validation locale possible en v0** faute de capteur LWD. Un protocole d'observation manuelle (rosée matinale 6h-8h sur 2-3 semaines printemps/été) est planifié comme procédure secondaire pour calibrer un éventuel biais correctif. À documenter dans un futur ADR si mis en œuvre.
- **Dépendance au calcul de Td** : Magnus-Tetens depuis T et HR (formule fermée standard, pas de dépendance externe).
- **Dépendance au calcul de R_n** : si R_s indisponible (cf. ADR-0006 stratégie rayonnement), Magarey dégrade à un mode "DPD pur" en perdant la correction radiative. Documenté comme heure dégradée dans les sorties.
- **Surveillance bibliographique** : la littérature LWD évolue (Rowlandson et al. 2015 *Plant Disease* 99, 310-319 — recommandations méthodologiques générales ; projets INRAE/CTIFL post-2020 type *Decid'Herbe*, *OptiProtect* à suivre). Toute mise à jour structurante sera tranchée en ADR successeur.
- **Cohérence aval** : les seuils de risque mildiou utilisés en aval (Mileos® CTIFL/INRAE, modèles Milsol) intègrent LWD ; l'utilisation de Magarey doit être documentée dans tout indice mildiou pour traçabilité.

## Références complémentaires

- Sentelhas, P.C., Dalla Marta, A., Orlandini, S., Santos, E.A., Gillespie, T.J., Gleason, M.L., 2008. *Suitability of relative humidity as an estimator of leaf wetness duration*. **Agric. For. Meteorol.** 148, 392-400. DOI: 10.1016/j.agrformet.2007.09.011 *[à vérifier]*. Étude comparative multi-modèles multi-sites — pilier méthodologique.
- Rowlandson, T., Gleason, M., Sentelhas, P., Gillespie, T., Thomas, C., Hornbuckle, B., 2015. *Reconsidering leaf wetness duration determination for plant disease management*. **Plant Disease** 99, 310-319. DOI: 10.1094/PDIS-05-14-0529-FE.
- Pedro, M.J., Gillespie, T.J., 1982. *Estimating dew duration. II. Utilizing standard weather station data*. **Agric. Meteorol.** 25, 297-310.
- Kim, K.S., Taylor, S.E., Gleason, M.L., 2004. *Development and validation of a leaf wetness duration model using a fuzzy logic system*. **Agric. For. Meteorol.** 127, 53-64.
