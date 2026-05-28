# meteo

Outils d'aide à la décision météo-climatique pour l'exploitation maraîchère bio
**La Petite Claye des Champs** (Pleine-Fougères, 35).

> **Statut** — cadrage en cours, code à venir. Voir `docs/decisions/` pour les
> décisions structurantes.

## Périmètre

Les apps ciblent le **maraîchage bio diversifié** (vente directe) et la
**pépinière de plants** internes à la ferme. Le blé pour transformation en
pain est hors périmètre.

## Architecture

Un **socle Python** partagé + trois apps utilisateur :

| Brique | Horizon | Hébergement |
|---|---|---|
| `socle` (lib `meteo_socle`) | — | code Python importable |
| App **veille & alertes** | 0-72 h | GitHub Actions + email matinal |
| App **opérationnelle** | 3-15 j (prév. plafonnée à 7 j) | Streamlit Community Cloud |
| App **climato & stratégie** | saison → projections | Quarto + GitHub Pages |

## Principes de conception

Sept principes transverses contraignent toutes les décisions du projet
(détails dans les ADRs) :

1. **Accompagner l'empirique, pas le remplacer** — ton informationnel, jamais prescriptif.
2. **Simplicité d'usage et durabilité** sans maintenance lourde.
3. **Multi-device** : web seul, idéalement mobile-friendly.
4. **Rigueur scientifique** : sources publiées citées (DOI / URL).
5. **Transparence totale** : chaque indicateur expose source, équation et code.
6. **Pas de boîte noire** : formules fermées publiées, pas de ML opaque.
7. **Agrégation multi-station par défaut** : aucune lecture mono-station pour
   les variables d'observation, compromis N × distance.

## Stack technique

- Python 3.12 via **conda** (`environment.yml`)
- **DuckDB** pour l'entrepôt local, **Parquet** pour les archives
- **Streamlit** (app opérationnelle), **Quarto** (app climato),
  **GitHub Actions** (veille & alertes)
- **Ruff** (format + check), **pytest**, **mypy**, **pre-commit**

## Décisions structurantes (ADRs)

Voir [`docs/decisions/`](docs/decisions/README.md).

## Données et confidentialité

Repo **public** sous discipline stricte (cf. [ADR-0001](docs/decisions/0001-publication-policy.md)) :
secrets jamais en clair, données opérationnelles ignorées par défaut,
géolocalisation au grain commune, pas de données personnelles tierces.

## Licence

À décider (ADR à venir).
