# Architecture Decision Records (ADRs)

Format Michael Nygard. Une décision structurante = un ADR court (~300-500 mots)
qui trace contexte, décision, et conséquences. Le format permet de
comprendre 18 mois plus tard *pourquoi* tel choix a été fait, sans plonger
dans l'archéologie git.

## Index

| ID | Titre | Statut |
|---|---|---|
| [0001](0001-publication-policy.md) | Publication policy du dépôt | Accepté |
| [0002](0002-sources-meteo-v0.md) | Sources météo retenues pour le v0 | Accepté |
| [0003](0003-characterization-testing.md) | Migration code `app-bilan-hydrique` par characterization testing | Accepté |
| [0004](0004-etp-fao-penman-monteith.md) | Modèle ETP : FAO Penman-Monteith horaire | Accepté |
| [0005](0005-modele-humectation-foliaire.md) | Modèle durée humectation foliaire (Magarey + Gleason croisé) | Accepté |
| [0006](0006-strategie-rayonnement-global.md) | Stratégie de couverture rayonnement global (cascade 2 niveaux) | Accepté |
| [0007](0007-modele-mildiou-tomate-sous-abri.md) | Modèle risque mildiou tomate sous abri (Smith periods 1956) | Accepté |

## Convention

- Numérotation à 4 chiffres + slug kebab-case.
- Statut parmi : `Proposé`, `Accepté`, `Déprécié`, `Remplacé par ADR-XXXX`.
- Tout changement structurant à une décision d'un ADR fait l'objet d'un ADR
  successeur qui le référence explicitement.
- Les principes de conception transverses (cf. README) sont la couche au-dessus
  des ADRs : les ADRs en sont des applications spécifiques.
