# ADR-0003 — Migration du code `app-bilan-hydrique` par characterization testing

## Statut

Accepté — 2026-05-28

## Contexte

Un code source antérieur existe : le dépôt `atantet/app-bilan-hydrique` sur GitHub. Il contient des modules scientifiquement substantiels et déjà validés en usage par l'auteur :

- `etp.py` — calcul horaire FAO Penman-Monteith complet (rayonnement net, vapor pressure deficit, fonction aérodynamique).
- `bilan.py` — bilan hydrique culture-spécifique, intégrant les coefficients culturaux ARDEPI et les profondeurs d'enracinement maraîchères.
- `geo.py` — sélection multi-stations par BallTree haversine et interpolation inverse-distance² (vers point de référence).
- `meteofrance.py` — accès aux APIs Météo-France DPObs / DPClim / DPPaquetObs (auth, conversions d'unités).
- `coefficients_culturaux_ardepi.json` — paramètres prêts à l'emploi.

Le nouveau projet `meteo` adopte des standards plus exigeants : packaging (pyproject), tests unitaires, type hints, docstrings avec sources bibliographiques (DOI / URL), ADRs, structure mono-repo socle + apps. La question est : **comment migrer le code existant sans introduire de régression silencieuse sur les calculs scientifiques** ?

Deux écueils symétriques à éviter :

- **Réécriture intégrale** : aligne tout d'un coup avec les nouveaux standards mais risque d'introduire des bugs sur des formules qui marchent.
- **Migration verbatim sans contrôle** : ne capte pas les éventuelles erreurs existantes ni les améliorations possibles, et n'aligne pas les standards.

## Décision

On adopte la méthode dite de **characterization testing** (Michael Feathers, *Working Effectively with Legacy Code*) en quatre phases ordonnées et traçables en commits séparés.

### Phase A — Filet de sécurité (avant toute modification)

- Extraire 5 à 10 cas de référence du code actuel : entrée météo connue → sortie ETP / bilan / interpolation connue.
- Fixer ces cas en tests `pytest` dans `tests/golden/` (`test_etp_golden.py`, `test_bilan_golden.py`, etc.).
- Critère de succès : tous tests verts avant toute action de phase B.

### Phase B — Migration syntaxique (commits petits, tests verts maintenus)

- Copier chaque module dans `socle/` du nouveau dépôt.
- Commits séparés par nature de changement, chacun gardant les golden tests verts :
  - `socle: import etp.py from app-bilan-hydrique (verbatim)` — copie nue
  - `socle: add type hints to etp module` — typage progressif
  - `socle: enrich docstrings with FAO X0490E references` — sources/DOI dans docstrings
  - `socle: split etp into pure function and IO wrapper` — refactor structurel si pertinent
- En cas de test rouge : commit suivant pour fix, ou revert.

### Phase C — Vérification scientifique indépendante (parallèle, non bloquante)

- Relire chaque formule contre sa source publiée (FAO X0490E pour ETP horaire, ARDEPI pour Kc, etc.).
- Toute divergence trouvée fait l'objet d'un **ADR de remédiation** précisant : nature de la divergence, source de référence, choix retenu (corriger vs justifier l'écart par un argument explicite, par exemple une adaptation au climat local).
- Les golden tests sont mis à jour seulement en bout de phase C, après ADR de remédiation.

### Phase D — Extension (nouvelles fonctionnalités aux standards d'emblée)

- Les nouveaux indices (humectation foliaire, mildiou, gel, fenêtres travail) sont écrits directement aux standards cibles : types, docstrings sourcées, tests, ADR pour chaque choix de modèle.

## Conséquences

- **Trace de tout choix** : chaque commit petit + chaque ADR rend visible et reviewable l'évolution du code.
- **Pas de régression silencieuse** : golden tests verts en permanence en phase B.
- **Bugs anciens détectables** : phase C peut révéler des écarts entre l'implémentation existante et la doctrine publiée, qui seront alors documentés et tranchés explicitement (corriger ou justifier).
- **Coût** : approche plus lente qu'une migration "brute". Coût accepté par alignement avec le principe de durabilité et de transparence.
- **Périmètre** : seuls les modules `etp.py`, `bilan.py`, `geo.py`, `meteofrance.py` et le fichier de coefficients sont concernés. Les notebooks de `app-bilan-hydrique` ne sont **pas** migrés ; leur logique d'orchestration sera ré-écrite dans le nouveau projet (apps Streamlit, GitHub Actions) selon les nouveaux principes.
