# État de l'art — Changement climatique & maraîchage bio diversifié

État de l'art **autoporté** sur les impacts du changement climatique pour le maraîchage biologique diversifié en vente directe, dans le secteur de **Pleine-Fougères** (Ille-et-Vilaine, baie du Mont-Saint-Michel). Horizon 30 ans, référentiel **TRACC**.

Ce dossier est **indépendant** des applications météo du dépôt : il a vocation à rester lisible et citable seul.

## Contenu

- **Phase 1 — impacts** (faite) : 8 axes thématiques + synthèse + 2 annexes (forage, axes émergents).
- **Phase 2 — adaptation** (à venir) : se calquera sur les mêmes axes.

Sources **scientifiques ou d'agences officielles** uniquement, qualifiées par un niveau de robustesse (cf. chapitre *Cadre et méthode*). Bibliographie complète (`references.bib`) doublée d'une **bibliographie annotée**.

## Structure

| Fichier | Contenu |
|---|---|
| `index.qmd` | Préface + Cadre & méthode |
| `00-synthese.qmd` | Synthèse — apprentissages à 30 ans |
| `01-climat.qmd` … `08-filiere.qmd` | Les 8 axes (climat, eau/forage, chaleur, phénologie/gel, bioagresseurs, sol, risques côtiers, filière) |
| `09-biblio-annotee.qmd` | Une fiche par source |
| `10-annexe-forage.qmd` | Annexe A — application au forage de La Petite Claye |
| `11-axes-emergents.qmd` | Annexe B — axes émergents à instruire |
| `references.qmd` / `references.bib` | Références citées |

## Construire le document

Prérequis : [Quarto](https://quarto.org).

```bash
# Aperçu live (HTML)
quarto preview

# Rendu HTML (sortie dans _output/)
quarto render --to html
```

Le rendu **PDF** est préconfiguré mais commenté dans `_quarto.yml` ; il nécessite une distribution LaTeX :

```bash
quarto install tinytex
# puis décommenter le bloc `pdf:` dans _quarto.yml
quarto render --to pdf
```

## Statut

Phase 1 (impacts) complète et rendue. Vérifications locales en cours (gouvernance de l'eau : SAGE, ZRE, arrêté-cadre sécheresse 35). Phase 2 (adaptation) non démarrée.
