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
| App **opérationnelle** | 3-15 j (prév. plafonnée à 14 j) | Streamlit Community Cloud |
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

## Cahier des charges

[`docs/panorama.md`](docs/panorama.md) — vue d'ensemble des 4 briques
(socle + 3 apps), décisions éclairées, indicateurs, vues, phasage.

## Décisions structurantes (ADRs)

[`docs/decisions/`](docs/decisions/README.md) — index des ADRs.

## Données et confidentialité

Repo **public** sous discipline stricte (cf. [ADR-0001](docs/decisions/0001-publication-policy.md)) :
secrets jamais en clair, données opérationnelles ignorées par défaut,
géolocalisation au grain commune, pas de données personnelles tierces.

## Lancer les apps en dev local

```bash
# Une fois : créer l'env conda
conda env create -f environment.yml

# À chaque session : activer
conda activate meteo

# Copier le template d'env et remplir SMTP + destinataire (App 1)
cp .env.example .env
```

### App 1 Veille (email matinal)

```bash
# Mode dry-run pour tester sans envoyer (ajouter dans config/veille.local.yaml :
#   diffusion: {envoi_reel: false})
python -m apps.veille
```

Le workflow `.github/workflows/veille.yml` exécute le même pipeline en
cron quotidien à 06:30 UTC. Pour l'activer en production, ajouter les
Secrets `VEILLE_SMTP_*`, `VEILLE_EMAIL_*` dans
*Settings → Secrets and variables → Actions*.

### App 2 Opérationnelle (dashboard Streamlit)

```bash
streamlit run apps/operationnelle/streamlit_app.py
```

Ouvre un navigateur sur <http://localhost:8501>.

**Déploiement Streamlit Community Cloud** :

1. Sur <https://share.streamlit.io>, *New app*.
2. Connecter le repo GitHub `meteo` (public).
3. *Main file path* : `apps/operationnelle/streamlit_app.py`.
4. *Python version* : 3.12 (Streamlit Cloud détecte `environment.yml`
   automatiquement et installe via conda).
5. Pas de Secret nécessaire — la config par défaut suffit.

URL résultante typique : `https://meteo-op-<random>.streamlit.app`.

## Tests

```bash
pytest tests/
```

## Licence

À décider (ADR à venir).
