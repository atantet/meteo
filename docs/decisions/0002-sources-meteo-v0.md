# ADR-0002 — Sources météo retenues pour le v0

## Statut

Accepté — 2026-05-28

## Contexte

Le socle a besoin de couvrir quatre horizons temporels distincts pour servir les trois apps (veille, opérationnelle, climato) :

1. **Climatologie historique 1958→** (rapports interannuels, normales, projections de base)
2. **Passé proche -1 an → J-1** (consolidé horaire ou journalier)
3. **Temps réel J-1 → J** (observations 24 h glissantes)
4. **Prévision J → J+7** (plafond explicite à 7 jours)

Les variables minimales requises pour calculer l'ETP FAO Penman-Monteith (cf. ADR-0004) et les indices agro retenus sont : température 2 m, humidité relative, vitesse du vent 10 m, rayonnement global, précipitation, plus point de rosée (dérivable) et pression (dérivable de l'altitude).

Trois familles de fournisseurs ont été comparées : Météo-France (open data officiel via portail-api : DPObs, DPClim, DPArome, DPArpege ; ré-analyse SAFRAN via climetlab/data.gouv.fr), Open-Meteo (passerelle multi-modèles avec API REST), ECMWF Copernicus CDS (lourd, GRIB direct).

Contraintes structurantes : exigence de transparence et de traçabilité (ADR-0001), exigence de durabilité sans maintenance lourde, exigence d'accès libre à toutes les variables aux bonnes granularités.

## Décision

Le socle v0 utilise trois sources, couplées via des interfaces abstraites pour permettre la substitution ultérieure.

| Horizon | Source v0 | Module | Format |
|---|---|---|---|
| Climatologie 1958→ | **SAFRAN Météo-France** 8 km, ré-analyse | `socle.sources.safran` | NetCDF via climetlab |
| Historique consolidé | **MF DPClim** | `socle.sources.meteofrance.DPClim` | CSV via portail-api |
| Temps réel J-1 → J | **MF DPObs / DPPaquetObs** | `socle.sources.meteofrance.DPObs` | CSV via portail-api |
| Prévision 0-7 j | **Open-Meteo** (passerelle multi-modèles : AROME France HD pour J0-J3, ARPEGE-EU pour J0-J4, ECMWF IFS pour J0-J7) | `socle.sources.openmeteo.Forecast` | JSON REST |

Chaque source implémente l'interface abstraite `socle.sources.base.SourceMeteo` exposant des méthodes `obtenir_observation(point, debut, fin)` / `obtenir_prevision(point, horizon)` / `obtenir_climatologie(point, periode)` selon les capacités du fournisseur.

Plafond de prévision fixé à **7 jours**. Aucune source n'est sollicitée au-delà.

## Justification

- **MF DPObs / DPClim** : déjà maîtrisés (réutilisation du code `app-bilan-hydrique`), source de référence française officielle, gratuite, autorisée pour usage non-commercial via portail-api.
- **SAFRAN** : grille 8 km adaptée au gradient côtier breton (Pleine-Fougères à ~20 km de la côte). ERA5 (25 km via Open-Meteo) écraserait ces gradients.
- **Open-Meteo prévision** : encapsule AROME France HD et ARPEGE-EU en API REST, évitant l'ingestion GRIB lourde (eccodes/cfgrib) tout en utilisant les modèles source officiels. Donne aussi accès à ECMWF IFS au-delà de 4 j, que MF ne distribue pas en open data direct.

## Conséquences

- **Risque durabilité Open-Meteo** : service tiers privé. Mitigation : abstraction `Forecast` substituable. Si Open-Meteo ferme, on écrit `MeteoFrancePrevisionArome(via cfgrib)` derrière la même interface, sans toucher au reste du code.
- **Risque rate-limit Open-Meteo** : 10 000 requêtes/jour en gratuit non commercial. Mitigation : cache local des prévisions dans DuckDB, refresh quotidien ou semi-quotidien.
- **Dépendances** : `climetlab` ou alternative pour SAFRAN, `requests` pour MF et Open-Meteo. Pas de `cfgrib` / `eccodes` requis en v0.
- **Token Météo-France** : un compte portail-api.meteofrance.fr est requis pour les APIs DPObs/DPClim. Token géré côté serveur (GitHub Actions Secrets, Streamlit Cloud Secrets), jamais en clair (cf. ADR-0001).
- **Tests** : chaque source doit avoir un mode `replay` à partir de jeux figés en parquet, pour tests reproductibles sans appel réseau.
- **Évolution** : un v1 pourra intégrer cfgrib pour ingérer AROME directement (résolution native plus fraîche) ou des capteurs locaux (`socle.sources.station_locale.Sencrop` / `Davis` / Pi+capteurs DIY).
