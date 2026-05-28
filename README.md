# meteo

Outils d'aide à la décision météo-climatique pour l'exploitation maraîchère bio
**La Petite Claye des Champs** (Pleine-Fougères, 35).

> **Statut** — v0 en production. Voir `docs/decisions/` pour les décisions
> structurantes et `docs/panorama.md` pour la vue d'ensemble.
>
> - Veille email — cron quotidien GitHub Actions (06:30 UTC).
> - Opérationnelle — Streamlit Community Cloud (en cours de mise en ligne).
> - Climato — rapport Quarto publié sur <https://atantet.github.io/meteo/>.

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
# Envoi réel via SMTP configuré dans .env :
python -m apps.veille

# Mode preview — écrit le HTML dans /tmp/veille.html sans toucher au
# SMTP. Pratique pour valider le rendu sans bombarder son inbox :
python -m apps.veille --preview /tmp/veille.html
xdg-open /tmp/veille.html
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

### Climatologie pré-calculée

Une normale journalière (T_min/T_max/T_moy par jour de l'année) sur
1991-2020 OMM (ERA5) est versionnée dans
`data/climato/normale_jour_lapetiteclaye.csv` et utilisée par :

- la courbe T° du mail Veille (overlay en pointillés gris),
- la table Opérationnelle (colonnes Normale T° + Écart normale).

Pour régénérer (rare, après changement de site ou de période OMM) :

```bash
python scripts/compute_normale_jour.py
```

Coût ~7-10 min (30 requêtes annuelles Open-Meteo Archive).

### App 3 Climato (rapport Quarto)

Quarto n'est pas un paquet Python — installer le binaire séparément :

```bash
# Linux (tarball officiel, recommandé)
QV=1.6.42
curl -LO "https://github.com/quarto-dev/quarto-cli/releases/download/v${QV}/quarto-${QV}-linux-amd64.tar.gz"
mkdir -p ~/.local/quarto
tar xzf quarto-${QV}-linux-amd64.tar.gz -C ~/.local/quarto --strip-components=1
echo 'export PATH="$HOME/.local/quarto/bin:$PATH"' >> ~/.bashrc

# Ou via apt sur Ubuntu (peut être plus ancien) :
#   sudo apt install quarto
```

Puis :

```bash
quarto render apps/climato/report.qmd --to html
# → produit apps/climato/report.html
```

**Déploiement GitHub Pages** : le workflow
`.github/workflows/climato-publish.yml` construit le rapport et le
publie sur <https://atantet.github.io/meteo/> à chaque modif du code
climato + tous les 1ers du mois. (Pages activé via
`gh api -X POST /repos/atantet/meteo/pages -f build_type=workflow`.)

## Tests

```bash
pytest tests/
```

## Licence

À décider (ADR à venir).
