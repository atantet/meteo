# CLAUDE.md — meteo

Ce projet suit le socle méthodologique commun : voir `~/projets/MéthodoClaude/CLAUDE.md` (organisation des fichiers, rigueur de sourçage, pipeline reproductible, git, permissions, mémoire, autonomie, tests). Ce fichier ne documente que les écarts et spécificités propres à ce projet — la mémoire persistante (`feedback_*`) reste la source de détail sur chaque règle et son cas d'origine ; ne pas la dupliquer ici.

## Périmètre de ce dépôt

Projet en production réelle (envois automatiques, dashboard Streamlit Cloud, site publié), le plus mature et le plus critique du portefeuille. Dépôt **public GPL-3.0** : pas de secrets, pas de données personnelles de tiers, géolocalisation au grain commune (ADR-0001).

## Permissions et exécution (friction la plus fréquente)

- Binaires d'environnement en **chemin absolu** (`~/.conda/envs/meteo/bin/{python,pytest,ruff,mypy,pre-commit,streamlit}`), jamais `conda activate` — l'allowlist matche par préfixe et un `&&` la casse.
- Une commande = un outil : jamais de pipe/for/heredoc composé.
- Pas de confirmation à redemander sur les commandes routinières en lecture seule (`pytest`, `ruff`, `git` non destructif).

## Mode autonome

Quand l'utilisateur est absent : minimiser les questions, trancher avec un parti pris documenté, poster un résumé de fin de tour. **Exceptions qui requièrent toujours confirmation explicite** : force-push, secrets, dépense, envoi réel d'un mail. L'autonomie n'est pas un blanc-seing — un module déjà livré en autonomie peut être remis en cause et abandonné après coup si l'usage réel ne le confirme pas.

## Rigueur scientifique et données

- Jamais de valeur fausse : une fenêtre de données partiellement couverte est omise, jamais extrapolée pour paraître complète.
- Toute substitution de modèle climatique/agronomique est vérifiée sur 30 ans de climatologie et confrontée à la doctrine terrain — un ratio 2-5× par rapport à l'attendu est un signal d'alerte même si la théorie sous-jacente est solide.
- Toute donnée transposée d'un autre contexte (filière, climat) porte sa provenance explicite.
- Une seule méthode officielle par phénomène affiché (ex. Vigilance Météo-France prévaut sur un calcul maison, sauf exception documentée).
- Les ADR sont de la documentation interne : jamais de référence à un numéro d'ADR dans un texte affiché à l'utilisateur final.
- Les guides de décision affichés portent toujours une action de mitigation d'un risque réel, jamais un conseil permissif — l'app invite à vérifier empiriquement, ne tranche jamais à la place de l'utilisateur.

## Tests

- Tester le pipeline complet avant de pousser, pas un simple smoke test d'import.
- Tester tous les modes d'une fonctionnalité (ex. matin/après-midi) avec un span de données réaliste — un jeu synthétique trop généreux masque des trous.
- Construire les fixtures dans les unités internes du socle (Kelvin, m/s) pour qu'une conversion oubliée casse un test au lieu de passer inaperçue.
- Dans toute cascade multi-source, attraper `requests.RequestException` en plus des exceptions métier — sinon une erreur réseau brute fait sauter toute une section au lieu de basculer sur la source suivante.

## Déploiement et suivi de bugs

- Un correctif qui s'exécute depuis `main` (mail cron, Streamlit Cloud) ne doit jamais dormir dans une PR de feature longue — vérifier la branche avant de committer un fix urgent.
- Suivi systématique des bugs via issues GitHub, même résolus dans la foulée ; fermeture seulement après confirmation visuelle en production **par l'utilisateur**, jamais par l'agent (pas d'eyeball navigateur/headless — générer une preview HTML à chemin fixe à la place).

## Écarts par rapport au socle commun

- Pas de pipeline `sources/scripts/livrables/validation` au sens strict du socle commun : l'architecture est organisée en `apps/` (veille, opérationnelle, atelier_irrigation, climato, bulletin_eau_mensuel) autour d'une librairie partagée `src/meteo_socle`, avec tests (`tests/`) et CI (`.github/workflows/`) comme mécanisme de validation à la place des logs `validation/*.log`.
