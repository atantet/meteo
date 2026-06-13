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
| [0008](0008-coefficient-etp-tunnel.md) | Coefficient de réduction ET₀ sous tunnel froid (k_tunnel) | Accepté |
| [0010](0010-doctrine-pragmatique-lwd.md) | Doctrine pragmatique LWD (rollback Smith ← HR ≥ 90 %, abandon Magarey théorique) | Accepté |
| [0011](0011-single-runs-api-runs-explicites.md) | Prévision via Single Runs API (runs explicites, analyse vs prévision) | Proposé · amendé par [0014](0014-prevision-officielle-mf-veille.md) (périmètre → App 2), [0016](0016-arpege-direct-mf-donnees-publiques.md) (source ARPEGE → MF direct) |
| [0012](0012-licence-gpl.md) | Licence du dépôt : GPL-3.0-or-later | Accepté |
| [0013](0013-temps-sensible-arome.md) | Temps sensible (pictogramme) dérivé des champs AROME (port MET Norway) | Accepté · part. déprécié par [0014](0014-prevision-officielle-mf-veille.md) (App 1) |
| [0014](0014-prevision-officielle-mf-veille.md) | Veille sur prévision officielle MF (heure locale) ; Opérationnelle sur ARPEGE + ECMWF (UTC) | Accepté · amendé par [0015](0015-fusion-app2-dans-mail-veille.md) (canal App 2) |
| [0015](0015-fusion-app2-dans-mail-veille.md) | Fusion App 2 dans le mail Veille (semaine du matin) + atelier irrigation | Accepté |
| [0016](0016-arpege-direct-mf-donnees-publiques.md) | ARPEGE en direct depuis MF Données Publiques (semaine) ; ECMWF reste Open-Meteo | Accepté · amende [0011](0011-single-runs-api-runs-explicites.md) (source ARPEGE) |
| [0017](0017-proba-semaine-mf-calibree.md) | Proba pluie de la semaine = proba officielle MF calibrée (signal autonome) ; remplace la maison IFS-ENS | Accepté · amende [0014](0014-prevision-officielle-mf-veille.md) / [0015](0015-fusion-app2-dans-mail-veille.md) (canal proba) |
| [0018](0018-ecmwf-direct-opendata.md) | ECMWF IFS HRES en direct depuis ECMWF Open Data (semaine) ; flag OFF par défaut | Accepté · prolonge [0016](0016-arpege-direct-mf-donnees-publiques.md), amende [0011](0011-single-runs-api-runs-explicites.md) |
| [0019](0019-guides-action-anti-risque.md) | Guides = action anti-risque (pas de permissif) ; retrait « nuits chaudes → portes ouvertes » ; saisons travail du sol validées climato ERA5 (octobre → fenêtre sèche) | Accepté |
| [0020](0020-atelier-cache-mf-partage.md) | Atelier irrigation : run ARPEGE MF partagé avec le mail (asset de release) en priorité, repli Open-Meteo ; résilience aux trous Open-Meteo | Accepté · s'appuie sur [0016](0016-arpege-direct-mf-donnees-publiques.md) / [0015](0015-fusion-app2-dans-mail-veille.md) |

## Convention

- Numérotation à 4 chiffres + slug kebab-case.
- Statut parmi : `Proposé`, `Accepté`, `Déprécié`, `Remplacé par ADR-XXXX`.
- Tout changement structurant à une décision d'un ADR fait l'objet d'un ADR
  successeur qui le référence explicitement.
- Les principes de conception transverses (cf. README) sont la couche au-dessus
  des ADRs : les ADRs en sont des applications spécifiques.
