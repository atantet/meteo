# ADR-0020 — Atelier irrigation : run ARPEGE MF partagé avec le mail (résilience)

Statut : **Accepté** · s'appuie sur [ADR-0016](0016-arpege-direct-mf-donnees-publiques.md)
(ARPEGE MF-direct) et [ADR-0015](0015-fusion-app2-dans-mail-veille.md) (atelier).

## Contexte

L'atelier irrigation (Streamlit, bilan hydrique interactif) récupère sa prévision
ARPEGE via **Open-Meteo** — alors que le mail (la semaine) est passé en **ARPEGE
MF-direct** (ADR-0016) pour fuir les **trous d'ingestion d'Open-Meteo**. Donc
l'atelier reste exposé à ces trous, et peut diverger du mail.

Passer l'atelier à MF-direct *en propre* est **impraticable** : le fetch WCS
(~10 min, ~500 requêtes, quota/min, secret) est incompatible avec une appli
**interactive** (Streamlit Cloud). Mais le mail a **déjà** payé ce fetch chaque
matin et mis le run en cache.

## Décision

Le mail **publie** son run ARPEGE MF-direct (le parquet du cache, au point, en
unités socle) en **asset de release GitHub** (`arpege-atelier`, nom de fichier
fixe écrasé chaque matin). L'atelier le **relit** :

- **Priorité au run MF partagé** (`calcul.charger_run_partage` →
  `obtenir_prevision`) s'il correspond au run **00Z du jour** ; **repli
  Open-Meteo** sinon (asset absent / réseau / parquet illisible / run périmé).
- Provenance **affichée** dans l'atelier (« Météo-France direct (run du mail) »
  vs « Open-Meteo (repli) ») + âge du run.
- Flag : `config/operationnelle.yaml → source_meteo.arpege_partage_url` (vide →
  Open-Meteo seul).
- Workflow Veille : étape `gh release upload --clobber` (best-effort, `always()`,
  `contents: write`) ; rien à publier si ARPEGE direct a échoué.

## Conséquences

**Positif**
- **Résilience** : un jour normal, l'atelier ne dépend **plus d'Open-Meteo** (il
  lit le run MF fiable déjà fetché). C'est la motivation première.
- **Cohérence** mail ↔ atelier : même run → même bilan de base (dérive ~1 %
  éliminée quand l'asset est frais).
- **Interactivité préservée** : Streamlit télécharge ~12 Ko (~0,3 s), **jamais**
  les 10 min du fetch MF (qui restent sur le runner).
- Pas de service nouveau (GitHub Releases, gratuit) ; pas de secret en lecture
  (asset public ; coords déjà publiques dans la config) ; `GITHUB_TOKEN` intégré
  en écriture.

**Négatif / limites**
- **Couplage** Streamlit Cloud ↔ release GitHub ↔ run matin (nouveaux modes de
  panne, gérés par le repli OM + l'affichage de l'âge).
- Cohérence **conditionnelle** : si le run matin échoue (MF muet) ou n'a pas
  encore tourné, l'atelier retombe sur Open-Meteo (donc la dérive réapparaît ces
  jours-là — assumé, c'est le cas dégradé).
- Mise à jour **1×/jour** (run 00Z) — cohérent avec le design « 1 maj/jour » du
  mail ; pas de rafraîchissement intra-journée.
