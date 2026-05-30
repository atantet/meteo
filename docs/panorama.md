# Panorama actualisé — cahier des charges des 4 briques

> **Statut** : v1 — issue du cadrage initial 2026-05-28. Document vivant ; toute
> modification structurante doit faire l'objet d'un ADR (cf. `docs/decisions/`).
> Toutes les briques s'inscrivent dans les **7 principes de conception**
> transverses (cf. README).

## Contexte et périmètre

Exploitation reprise : **La Petite Claye des Champs** (Pleine-Fougères, 35),
porteur DJA, EARL unipersonnelle nouvelle. Acte authentique visé 02/2027,
première saison opérationnelle 2027.

Périmètre des apps : **maraîchage bio diversifié** (vente directe, principal).
Blé pour pain *hors périmètre*. Pépinière interne *hors périmètre v0* —
module abandonné délibérément 2026-05-29.

## Architecture d'ensemble

```
                    ┌─────────────────────────────────────┐
                    │     socle  (lib  meteo_socle)       │
                    │  ┌───────────┐  ┌─────────────┐     │
                    │  │ sources   │  │ geo (IDW²)  │     │
                    │  │ DPObs     │  │ multi-stat. │     │
                    │  │ DPClim    │  └─────────────┘     │
                    │  │ SAFRAN    │  ┌─────────────┐     │
                    │  │ OpenMeteo │  │ indices     │     │
                    │  └───────────┘  │ ETP, bilan, │     │
                    │  ┌───────────┐  │ gel, mildiou│     │
                    │  │ entrepot  │  │ LWD, etc.   │     │
                    │  │ DuckDB    │  └─────────────┘     │
                    │  │ +parquet  │  ┌─────────────┐     │
                    │  └───────────┘  │ meta (traç.)│     │
                    │                 └─────────────┘     │
                    └──────────┬──────────────────────────┘
                               │ import
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
   ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
   │ App 1 Veille    │ │ App 2 Opér.     │ │ App 3 Climato   │
   │ 0–72 h          │ │ 3–15 j (≤ 7 j)  │ │ saison → DRIAS  │
   │ GH Actions cron │ │ Streamlit Cloud │ │ Quarto + Pages  │
   │ email matinal   │ │ dashboard       │ │ rapports HTML   │
   │                 │ │                 │ │ + PDF           │
   └─────────────────┘ └─────────────────┘ └─────────────────┘
```

---

## 1. Socle `meteo_socle` (bibliothèque Python)

### Rôle

Pas d'UI propre — importable par les trois apps. Centralise ingestion des
sources, agrégation spatiale, calcul d'indices et traçabilité des
métadonnées.

### Modules

- **`meteo_socle.sources`** — interface abstraite `SourceMeteo` (cf.
  [ADR-0002](decisions/0002-sources-meteo-v0.md)) avec implémentations :
    - `MeteoFranceDPObs` (observations 24 h glissantes)
    - `MeteoFranceDPClim` (historique consolidé)
    - `SafranReanalysis` (climato 1958→, via climetlab)
    - `OpenMeteoForecast` (prévision 0-7 j, multi-modèles)
- **`meteo_socle.geo`** — sélection multi-station BallTree haversine, agrégation
  inverse-distance² (principe n°7), avec exception R_s explicite
  (cf. [ADR-0006](decisions/0006-strategie-rayonnement-global.md)).
- **`meteo_socle.indices`** — un module Python par indice, docstring contenant
  équation, hypothèses, références bibliographiques DOI/URL, exemples
  testés (cf. principes n°4 et n°5).
- **`meteo_socle.entrepot`** — DuckDB local + parquet archives, conventions
  de schéma de table.
- **`meteo_socle.meta`** — métadonnées de traçabilité (`source_niveau`,
  `stations_utilisees`, `qualite`, etc.) — alimente le principe n°5.

### Catalogue d'indices

**MVP (v0)** :

- ETP FAO Penman-Monteith horaire (cf. [ADR-0004](decisions/0004-etp-fao-penman-monteith.md))
- Bilan hydrique simple (P − ETP cumulé)
- Risque gel (T° min + seuils, défaut −2 °C à valider)
- Risque canicule (T° max + heat stress, défaut 32 °C à valider)
- Fenêtres travail (heuristique pluie 24-72 h + vent + portance sol simple)

**v0 livré (depuis 2026-05-29)** :

- Risque mildiou tomate Smith periods 1956 (cf. [ADR-0007](decisions/0007-modele-mildiou-tomate-sous-abri.md)),
  intégré aux 3 apps (mail Veille, dashboard Op, rapport Climato).
- Bilan hydrique plein champ (Kc × ET₀, coefficients ARDEPI) — App 2 Op.
- Bilan hydrique sous tunnel (k_tunnel = 0.70 défaut, cf.
  [ADR-0008](decisions/0008-coefficient-etp-tunnel.md)), modèle sol
  complet avec carry-over RU jour par jour — App 2 Op.
- Pictogrammes météo Meteocons (MIT, Bas Milius) basés sur codes
  WMO 4677 d'Open-Meteo :
  - **Mail Veille** : bande "Tendance 48 h" en tête (3 fenêtres
    matin/midi/soir × 2 jours, AROME France HD 1.3 km).
  - **App 2 Op** : section "Tendance 7 jours" comparaison ARPEGE
    vs ECMWF IFS avec colonne accord ✓/⚠ (visualisation
    multi-modèles).
  - **Climato** : section "Calendrier annuel des conditions
    météo" (distribution mensuelle sur 30 ans en 7 catégories
    agrégées).

**v1 (priorité bioagresseurs bio)** :

- Humectation foliaire Magarey DPD/NWP 2005 (cf.
  [ADR-0005](decisions/0005-modele-humectation-foliaire.md)) —
  substituer le proxy LWD CART Gleason 1994 (déjà en place depuis
  2026-05-29) par Magarey DPD/NWP quand le papier sera accessible.
- Risque mildiou pomme de terre (modèle à choisir entre Hyre, Mishra, SimMip — ADR à venir)
- Calibration locale k_tunnel après une saison d'observation
  (compteur eau vs prédiction app).

**v2 (extensions)** : alternaria, oïdium, botrytis, sommes thermiques par culture, etc.

### Critères MVP

- 4 sources implémentées avec mode `replay` (lecture parquet figé pour tests)
- 5 indices MVP avec golden tests (cf. [ADR-0003](decisions/0003-characterization-testing.md))
- API stable documentée (mkdocs ou Quarto)
- Couverture tests > 80 % sur indices et `geo`
- Conforme aux 7 principes (revue manuelle au moment du tag v0)

### Phasage

| Version | Sources | Indices | Notes |
|---|---|---|---|
| v0 | MF DPObs + Open-Meteo | 5 MVP | DuckDB local, mode replay |
| v1 | + SAFRAN | + bioagresseurs + bilan hydrique culture | Pour app climato |
| v2 | + capteurs locaux | + alternaria, oïdium, sommes T° | Si capteurs ferme installés |

### Hypothèses propres / questions ouvertes

- Lieu unique (centroïde Pleine-Fougères) en v0, multi-parcelles en v1+
- DuckDB local suffit ; pas de PostgreSQL en v0
- Pas de DVC ; snapshots datés en parquet
- Makefile (cohérence stack existante), pas de Just
- Choix exact des modèles mildiou et clearness ratio à instruire en ADRs successeurs

---

## 2. App 1 — Veille email matinal (GitHub Actions)

### Décisions matinales éclairées — *hypothèses à valider*

1. Bâcher / dévoiler ce soir ? (gel attendu nuit prochaine, voile P17/P30)
2. Aérer ou fermer les serres / tunnels aujourd'hui ? (canicule, gel, mildiou)
3. Pulvérisation préventive bio aujourd'hui ? (pluie imminente = lessivage
   cuivre/soufre ; pression mildiou montante)
4. Fenêtre de travail demain ? (go/no-go semis, repiquage, désherbage
   mécanique, récolte)
5. Anticiper arrosage tunnel ? (bilan hydrique tendu)

### Données d'entrée

Prévision 0-72 h depuis le socle (Open-Meteo v0) + DPObs J-1 pour
comparaison.

### Indicateurs envoyés

T° min nuit prochaine + alerte gel ; T° max jour + alerte canicule ; cumul
pluie 24/48/72 h + alerte pluie intense ; vent max + alerte vent fort ;
risque mildiou + tendance ; synthèse fenêtre travail 24-72 h ; bilan
hydrique 7 j.

### Format email

- Sujet : « Veille [DATE] — [alertes prioritaires] »
- En-tête : bandeau alertes seuils franchis (rouge / orange / vert)
- Résumé « à savoir » en 3-5 puces, ton **informationnel** (principe n°1)
- Tableau condensé J / J+1 / J+2
- Chaque indicateur : lien vers sa **fiche indice** sur Pages (principe n°5)

### Cron

GitHub Actions, heure à confirmer (par défaut 6 h Paris).

### Critères MVP

- Email quotidien à heure fixe
- 3 alertes basiques (gel, canicule, pluie intense)
- Lisible smartphone (principe n°3)
- Lien vers la source de chaque indicateur

### Phasage

| Version | Format | Indicateurs | Notes |
|---|---|---|---|
| v0 | texte brut | 3 alertes | MVP rapide |
| v1 | HTML stylé | 5-7 + tendances | Lien fiches indice |
| v2 | HTML + personnalisé | par culture / parcelle | + accusé réception, 2e envoi soirée si gel imminent |

### Hypothèses propres / questions ouvertes

- Heure d'envoi : 6 h Paris (à valider)
- Second envoi soirée si gel imminent J+1 ?
- Les 5 décisions matinales : hypothèses, à valider terrain
- Seuils défaut : gel = −2 °C, canicule = 32 °C, pluie intense = 20 mm/24 h,
  vent fort = 60 km/h — à valider
- Destinataires : Alexis seul en v0, équipe en v1+

---

## 3. App 2 — Opérationnelle 3-15 j (Streamlit Cloud)

### Décisions éclairées

1. Planifier la semaine (semis, repiquage, désherbage mécanique, récolte)
2. Anticiper traitement bio préventif (24-48 h avant pic de pression)
3. Décider l'irrigation sous abri vs plein champ sur 7-10 j
4. Anticiper protections (voile, paillage, fermetures)

### Données d'entrée

Prévision 3-15 j (Open-Meteo ensemble v0, mix MF ARPEGE + AROME v1) +
observations terrain saisies à la main.

### Vues

- **Vue Semaine** : tableau jour × indicateur, codes couleur
- **Vue Indice** : courbe 15 j avec seuils et zones de risque (chaque point
  est cliquable → métadonnées)
- **Saisie observations bio** : date + parcelle + observation libre + photo
  optionnelle (couplage rétro avec météo des 14 j passés pour modèle local)
- **Expand « vérifier la source »** systématique sur chaque indicateur
  (principe n°5)

### Critères MVP

- Vue Semaine fonctionnelle avec 4-5 indicateurs (gel, canicule, pluie,
  fenêtre travail, bilan hydrique)
- Mise à jour quotidienne automatique
- URL Streamlit Community Cloud accessible
- Testé sur mobile réel (principe n°3)

### Phasage

| Version | Vue Semaine | Saisie obs | Multi-parcelles |
|---|---|---|---|
| v0 | 4 indices, lecture seule | — | 1 point ferme |
| v1 | + indices bioagresseurs + bilan culture-spécifique | ✓ | — |
| v2 | + comparaison interannuelle | mobile dédié si retour terrain | ✓ |

### Hypothèses propres / questions ouvertes

- Saisie observations : Streamlit responsive suffit en v1, dédié mobile en
  v2 si retour terrain le justifie
- Granularité spatiale : 1 point ferme en v0, multi-parcelles en v1

---

## 4. App 3 — Climato & stratégie (Quarto + GitHub Pages)

### Décisions éclairées

1. Choix variétal annuel (résistance gel / chaleur / sécheresse vs climatologie locale)
2. Calendrier cultural adapté (décalages dates clés selon évolution climat)
3. Stratégie pluri-annuelle (investissement abris, irrigation, choix culture forte VA, adaptation climat)
4. Bilan rétrospectif saison N (qu'est-ce qui a marché vs climat réel ?)

### Données d'entrée

Historique SAFRAN 1958→ (8 km, gratuit via climetlab / data.gouv.fr) +
projections DRIAS 2030 / 2050 / 2100.

### Indicateurs / analyses

- Distributions interannuelles T° / pluie / ETP par mois (boxplots, quantiles)
- Tendances et ruptures (régressions, points de changement)
- Dates clés : premier gel, dernier gel, début et fin de saison végétative,
  longueur saison
- Nombre jours canicule, jours pluvieux > 10 mm
- Cumuls saisonniers ETP, P, P − ETP
- Comparaison année courante vs normales 1991-2020 et 1961-1990
- Projections DRIAS sur ces mêmes indicateurs

### Vues / livrables

- Rapport « Climatologie locale Pleine-Fougères » — premier gros livrable,
  HTML + PDF
- Rapport « Bilan saison N » — annuel, en fin de saison
- Rapport « Variétés candidates » — en amont d'un choix variétal annuel
- Tous les rapports : **chunks de code visibles par défaut** (principe n°5),
  références BibTeX, citations DOI quand applicable

### Critères MVP

- Un rapport « Climatologie Pleine-Fougères » publié sur Pages
- 3-4 figures clés (régime pluie, T° saisonnière, dates gel, ETP saison)
- Source SAFRAN intégrée
- HTML + PDF générés depuis Quarto

### Phasage

| Version | Livrable | Notes |
|---|---|---|
| v0 | Rapport climato statique | Avant saison 2027 si possible |
| v1 | + Bilan saison annuel + DRIAS | En fin de chaque saison |
| v2 | + Rapport variétés + Observable JS | Pour exploration interactive |

### Hypothèses propres / questions ouvertes

- Source historique : SAFRAN (8 km) en v0 — confirmé
- Période de référence climatologique : 1991-2020 OMM (par défaut) — à valider
- Date cible premier rapport climato : avant saison 2027 ? — à confirmer

---

## 5. Phasage d'ensemble — ordre de construction recommandé

**Phase 0 — Bootstrap** (✅ fait)

Repo créé, structure mono-repo, ADRs 0001-0006 initiaux, settings
permissions.

**Phase 1 — Socle minimal**

- ADR-0003 phase A : extraction des cas de référence du code existant
  `app-bilan-hydrique`, fixation en golden tests pytest
- Migration verbatim des modules `etp.py`, `bilan.py`, `geo.py`,
  `meteofrance.py` dans `src/meteo_socle/`
- Refactoring incrémental en commits séparés : types, docstrings sourcées,
  packaging
- Interface abstraite `SourceMeteo` + `OpenMeteoForecast`
- Entrepôt DuckDB local
- Tests verts ; tag v0 du socle

**Phase 2 — App 1 Veille minimale**

- Cron GitHub Actions
- 3 alertes (gel, canicule, pluie intense) via socle
- Email texte simple
- Validation utilisateur : « l'email arrive le matin et m'est utile ? »

**Phase 3 — App 2 Opérationnelle MVP**

- Streamlit Cloud déployé
- Vue Semaine 4 indicateurs
- Lien vers App 1 et Pages

**Phase 4 — App 3 Climato MVP**

- Source SAFRAN intégrée
- Rapport « Climatologie Pleine-Fougères » publié sur Pages

**Phase 5+ — Extensions**

- Indices bioagresseurs (socle + apps)
- Capteurs locaux à la ferme
- Bilan saison annuel + projections DRIAS (App 3)

---

## 6. Hypothèses ouvertes — auto-critique transverse

Ce qui n'est *pas encore* tranché et nécessitera des décisions ultérieures
(souvent en ADR successeur) :

- **Décisions matinales de la veille** : 5 hypothèses à valider terrain.
- **Heure d'envoi email** : 6 h Paris par défaut, à valider.
- **Seuils par défaut alertes** : gel, canicule, pluie, vent — à valider par
  vos retours d'expérience.
- **Saisie observations terrain** : Streamlit responsive ou interface mobile
  dédiée ?
- **Cible date premier rapport climato** : avant saison 2027 ?
- **Modèle mildiou pomme de terre précis** : Hyre vs Mishra vs SimMip — ADR
  à instruire.
- **Modèle clearness ratio** pour fallback R_s : Black 1956 vs Kasten &
  Czeplak 1980 — ADR à instruire.
- **Vérification équipement R_s** de RENNES-ST JACQUES et ST BRIEUC (cf.
  ADR-0006 évolution v1+) — un appel DPClim dès que le socle a accès au
  token MF.
- **Verrouillage RU / RFU et coefficients culturaux** sur l'exploitation
  réelle (textures des parcelles, profondeurs d'enracinement constatées) —
  travail terrain à conduire au démarrage saison 2027.
- **Licence du dépôt** — à décider (ADR à venir).

Toute réponse à ces points peut soit modifier le panorama, soit déclencher
un ADR. Le panorama est révisé en conséquence.
