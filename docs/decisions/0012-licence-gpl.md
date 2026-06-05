# ADR-0012 — Licence du dépôt : GPL-3.0-or-later

## Statut

Accepté — 2026-06-05. Tranche la question laissée ouverte par
[ADR-0001](0001-publication-policy.md) (« License à décider »).

## Contexte

Le dépôt est public (ADR-0001) mais sans licence explicite — par défaut, du
code publié sans licence reste « tous droits réservés », ce qui contredit la
démarche d'ouverture du porteur et empêche toute réutilisation.

Élément déclencheur concret : pour fiabiliser le pictogramme de la Veille
(cf. [ADR-0013](0013-temps-sensible-arome.md)), la meilleure méthode
disponible est l'algorithme de symbole temps de **MET Norway**
(`metno/weather_symbol`), publié sous **GPL-2.0-or-later**. Porter ce code
crée une œuvre dérivée : la GPL impose alors que le dérivé soit lui-même
distribué sous GPL. Réutiliser du code GPL **exige** donc une licence
compatible côté dépôt.

## Décision

Le dépôt est placé sous **GNU General Public License v3.0 ou ultérieure**
(`GPL-3.0-or-later`).

- Texte intégral dans `LICENSE` (GPLv3).
- Métadonnée `license = "GPL-3.0-or-later"` dans `pyproject.toml`.
- Mention dans le `README`.

GPLv3 (plutôt que v2) car c'est la version courante ; elle est **compatible
avec l'incorporation de code GPL-2.0-*or-later*** (la clause « or later »
autorise la redistribution sous v3). Chaque fichier portant du code tiers
GPL conserve un en-tête créditant l'auteur d'origine (cf. en-tête de
`src/meteo_socle/indices/temps_sensible.py`).

## Conséquences

- **Copyleft** : toute redistribution d'un dérivé du dépôt doit rester sous
  GPL et fournir le code source. Acceptable et même souhaité ici (transparence
  scientifique, principe n°6 « pas de boîte noire »).
- **Réutilisation de code GPL débloquée** : MET Norway aujourd'hui, et tout
  autre code de service météo national publié sous GPL demain.
- **Dépendances** : GPLv3 est compatible avec les bibliothèques sous licences
  permissives (BSD/MIT/Apache-2.0 — pandas, numpy, pvlib, requests). Aucune
  dépendance actuelle n'est sous une licence incompatible.
- **Pas AGPL** : bien que les apps soient déployées en SaaS (Streamlit Cloud),
  on retient la GPL simple, pas l'AGPL — pas d'obligation de fournir la source
  aux utilisateurs du service web au-delà de ce que la publication GitHub offre
  déjà. Révisable par ADR successeur si besoin.
- **Icônes** : les jeux d'icônes embarqués gardent **leur propre** licence
  (Meteocons MIT, etc., cf. ADR-0013) — la GPL du dépôt ne les absorbe pas
  (ce sont des ressources agrégées, pas du code lié).

## Alternatives écartées

- **MIT/Apache-2.0** (permissif) : simple, mais **incompatible** avec
  l'incorporation de code GPL → aurait interdit le portage MET Norway et forcé
  à réinventer des seuils moins bien sourcés.
- **AGPL-3.0** : copyleft réseau, plus contraignant que nécessaire pour l'usage
  actuel.
