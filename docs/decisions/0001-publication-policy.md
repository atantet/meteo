# ADR-0001 — Politique de publication du dépôt

## Statut

Accepté — 2026-05-28

## Contexte

Le dépôt `meteo` est hébergé sur GitHub en **public**. Choix justifié par :

- alignement avec la démarche d'ouverture du porteur (DJA, maraîchage bio, partage avec l'écosystème) ;
- accès gratuit illimité aux runners GitHub Actions et à Streamlit Community Cloud (les deux exigent ou favorisent fortement le repo public) ;
- exigence de transparence scientifique (cf. ADR-0004 et suivants) qui se prête à la publication ouverte.

Le contrepoids est le risque de fuite de **données opérationnelles ou personnelles** liées à l'exploitation La Petite Claye des Champs (Pleine-Fougères, 35) : relevés de capteurs, observations terrain, géoréférencement parcellaire fin, identités tiers (voisins, clients AMAP, équipe future). Sans discipline, un repo public devient un canal involontaire de divulgation.

## Décision

Cinq règles s'appliquent à tout commit poussé sur la branche publique du dépôt.

1. **Secrets jamais en clair.** Clés d'API (Météo-France, autres) chargées via `.env` local ignoré + `.env.example` versionné comme template vide. Référence d'usage via `os.environ`. Pour le déploiement, secrets stockés côté plateforme (Streamlit Cloud Secrets, GitHub Actions Secrets), jamais dans le code.

2. **Données opérationnelles ignorées par défaut.** Les chemins `data/raw/`, `data/observations/`, `data/sensors/` sont listés dans `.gitignore`. Seules les données publiques (climatologie SAFRAN, jeux Open-Meteo génériques, jeux de référence pour tests) sont versionnées.

3. **Géolocalisation calibrée par usage.** Le **site de référence** des apps est *La Petite Claye, 35610 Pleine-Fougères* (48.5420 N, -1.6155 W, altitude ~30 m). Adresse publiquement disponible (cadastre, OSM), donc inscrite en clair dans le code et la configuration par défaut afin que les apps fonctionnent dès le clone. En revanche, les coordonnées **exactes des parcelles** (polygones cultivés à l'échelle décamétrique), de bâtis tiers ou d'éléments sensibles restent locales ou paramétrées dans des fichiers de configuration ignorés (`.env`).

4. **Pas de données personnelles tierces.** Aucune information identifiante de voisins, clients, employés futurs, ou tout tiers n'apparaît dans le repo, ni dans le code, ni dans les commentaires, ni dans les logs versionnés.

5. **Périmètre publié documenté.** Le présent ADR définit ce qui est publié (code, méthodologie, indices, jeux de référence) et ce qui ne l'est pas (relevés capteurs, calendrier cultural personnel, traitements). Tout cas ambigu sera tranché par un ADR ultérieur dédié.

## Conséquences

- Les fichiers `.env.example`, `.gitignore`, `data/raw/.gitkeep` (vide) sont créés à la racine du repo dès le bootstrap.
- Une revue manuelle « pré-public » de chaque branche feature avant merge est requise tant qu'aucun outil automatique de scan de secrets n'est intégré (ajouter `gitleaks` ou équivalent en pre-commit reste un sujet ouvert).
- Si une donnée sensible est divulguée par erreur, la procédure standard est : retrait + rotation des secrets + entrée dans un journal d'incidents, **pas** seulement un `git rm` qui laisse la donnée dans l'historique. Documenter le cas échéant en ADR de remédiation.
- Cette politique est révisable. Tout changement (par exemple un passage en privé) doit faire l'objet d'un ADR successeur explicite.
