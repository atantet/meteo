# ADR-0014 — Veille sur prévision officielle Météo-France (heure locale) ; Opérationnelle sur ARPEGE + ECMWF (UTC)

## Statut

**Accepté** (2026-06-06). **Amende [ADR-0011](0011-single-runs-api-runs-explicites.md)**
en restreignant son périmètre à l'**App 2** (la Veille quitte Single Runs).
**Déprécie partiellement [ADR-0013](0013-temps-sensible-arome.md)** : le picto MET
Norway fabriqué n'est plus utilisé par aucune des deux apps en primaire (App 1 prend
le picto MF ; App 2 abandonne les pictogrammes) ; le code reste dans le socle comme
repli. Hors périmètre : climato/archives (SAFRAN/ERA5).

## Contexte

Déclencheur (2026-06-05) : pas de **picto orage validé** via Open-Meteo. L'exploration
MF-directe (2026-06-05/06) a montré que **le WWMF n'existe pas dans le public MF** et
que le **MF-direct GRIB est lourd** (pas d'endpoint point) — mais que la **prévision
officielle MF** (`webservice.meteofrance.com`, backend appli/site) expose **au point,
en un JSON**, le pictogramme (orage inclus), une **proba calibrée** et
T/HR/vent/pluie/nébulosité, en **roulant**.

Deux natures de besoin se séparent **par application**, et le porteur a tranché un
**partage net** (sans série partagée entre les deux) :

- **App 1 (Veille)** = « quel temps dans les prochaines ~48 h ? » → réponse
  d'**autorité**, fraîche, picto + proba prêts. **Prévision officielle MF.**
- **App 2 (Opérationnelle)** = intégrer la météo dans la décision, **jauger
  l'incertitude** (comparaison de modèles, spread, reproductibilité, 10 j). **Single
  Runs Open-Meteo.**

### Faits vérifiés par sonde (2026-06-06)

**Prévision officielle MF** (`webservice.meteofrance.com`, Pleine-Fougères) :
- `dt` horaire fourni ; **portion au pas horaire jusqu'à ~00:00 UTC de J+2**
  (mesuré : ~45 h pour un fetch du matin, ~30 h pour un fetch du soir) ; au-delà
  pas 3 h puis 6 h ; `probability_forecast` 3 h→6 h ~10 j ; `daily_forecast` 15 j.
- **Ni rayonnement ni ETP** (seul `iso0`).
- Roulante, `updated_on` ~20 min de fraîcheur (FAQ MF : MàJ ~15 min). Pas de run.
- Point calé sur la commune la plus proche (échelle communale, assumée).

**Single Runs Open-Meteo** (runs 00Z/12Z) :
- **ARPEGE Europe : 102 h ≈ 4,2 j.** **ECMWF IFS025 : 362 h ≈ 15 j** (horaire tout
  du long). AROME : ~48 h (non retenu, cf. D2).

### Contrainte assumée

La prévi MF est une **source d'autorité opaque** (fusion + expertise humaine, non
reproductible, accès non officiel hors Etalab). On l'assume pour le **verdict** (pas
pour le calcul scientifique), dans la lignée de l'exception transparence d'
[ADR-0006](0006-strategie-rayonnement-global.md).

## Décisions

### D1 — App 1 (Veille) : prévision officielle MF, heure locale, sans ETP

La Veille répond à « quel temps dans les prochaines ~48 h ? » à partir de la **seule**
prévision officielle MF (picto orage inclus, proba, T/pluie/vent/nébulosité —
auto-cohérents, le bug d'ADR-0013 disparaît). **L'App 1 abandonne l'ETP et tout ce
qui s'y rapporte** (bilan, indices dérivés du rayonnement) : la prévi MF ne fournit pas
le rayonnement, et ce n'est pas l'objet de la Veille. **L'App 1 ne touche plus
Open-Meteo.** **L'App 1 conserve ses cartes synoptiques et ses séries temporelles**
(graphiques) ; les séries sont désormais alimentées par la prévi MF et **rendues en
heure locale** (cf. D4). Étiquette affichée : « Prévision officielle Météo-France,
mise à jour {updated_on} » (jamais « ADR-XXXX » dans le texte affiché).

### D2 — App 2 (Opérationnelle) : Single Runs UTC, ARPEGE + ECMWF, sans picto

L'App 2 reste sur **Single Runs Open-Meteo, en UTC** (ADR-0011). **Deux modèles
seulement : ARPEGE (court, ≤ ~4 j) et ECMWF (tendance 10 j)** — **AROME est retiré**
(la maille fine 0-48 h est désormais couverte par la Veille MF, et l'App 2 vise le
spread/tendance). **Aucun pictogramme** dans l'App 2 (séries quantitatives + spread).
La **proba de pluie est conservée** (ensemble ECMWF IFS-ENS, calcul socle transparent,
ADR-0011). **Le périmètre d'ADR-0011 est restreint à l'App 2.**

### D3 — Deux apps distinctes : plus de série partagée

Le porteur acte un **partage net** : App 1 = verdict d'autorité MF (heure locale) ;
App 2 = exploration modèles (UTC). **Il n'y a plus de « ligne de référence MF » dans
l'App 2.** Conséquence assumée : la coïncidence stricte e-mail ↔ dashboard d'ADR-0011
(D2) **n'est plus garantie** — ce sont deux outils de natures différentes (une réponse
unique d'autorité vs un faisceau de modèles). Comme l'App 2 n'affiche plus de picto ni
de verdict orage, il n'y a pas de doublon de méthode avec la Veille (« une seule
méthode par phénomène » respecté).

### D4 — Veille : cadence & fenêtre, en heure locale, horaire seul

- **Tout en heure locale** (Europe/Paris) : fenêtre, bins, labels (réversion du
  tout-UTC d'ADR-0011 D5 pour l'App 1 — les labels deviennent honnêtes en local).
- **Cron : 6 h 30 et 18 h 30 heure locale** (2×/jour). Critères : (a) au plus tôt,
  avec **marge sur l'actualisation Vigilance** (publiée ~6 h / ~16 h locales) ;
  (b) rester sur des **périodes de 6 h entières** (le décalage +30 min place l'envoi
  juste après le début de la période courante, qui est donc entièrement prévue).
- **Prévision horaire uniquement** → horizon **adaptatif** : la portion horaire MF va
  jusqu'à ~00:00 UTC de J+2 (~45 h le matin, ~30 h le soir).
- **Représentation par période de 6 h** : nuit 0-6 / matin 6-12 / après-midi 12-18 /
  soir 18-24 (heure locale).
- **Découpage sur les périodes pleines, jamais sur l'heure du cron.** La série MF ne
  démarre **pas** à l'heure d'envoi : l'API renvoie une **queue d'heures déjà écoulées**
  (1ʳᵉ échéance = heure ronde ~1 à 3 h **avant** le fetch ; sonde : 1ʳᵉ heure 05:00 pour
  un fetch de 06 h 21). On **slice donc sur les périodes de 6 h** :
  - **première période affichée = première période de 6 h entièrement future**
    (les heures de tête déjà écoulées, partielles, sont exclues) ;
  - **dernière période affichée = dernière période de 6 h pleine** intégralement
    couverte par l'horaire.

  La période courante est donc toujours complète : à l'envoi de **6 h 30**, « matin »
  (6-12) est entièrement future → première période affichée (la queue 05:00 tombe dans
  « nuit », partielle → exclue) ; à **18 h 30**, « soir » (18-24) est la première.
  Exemple (sonde matin 06 h 21) : affiche aujourd'hui matin/après-midi/soir + demain
  nuit/matin/après-midi/soir, **stop au soir de J+1**.
- Plus de table créneau→run, d'ancre run, de stitch, de calibration de latence.
- *Option différée* : un mode d'affichage **horaire** (pas 1 h) en plus des périodes.

### D5 — Opérationnelle : 10 j, UTC, deux modèles aux horizons distincts

Tendance **10 j en UTC**. Horizons mesurés : **ARPEGE 102 h (≈ 4,2 j)** → couvre
J→J+4 (court terme, fin de maille) ; **ECMWF 362 h (≈ 15 j)** → **porte la tendance
jusqu'à J+10** (et au-delà). Les deux séries étant **horaires tout du long**, on garde
des **bins 12 h jour/nuit UTC** sur tout l'horizon (pas besoin de repli quotidien).
Chaque série porte son run explicite (ADR-0011 D7).

### D6 — ETP/bilan : conservée dans l'App 2 seulement

L'**ETP reste calculée par le socle** (FAO Penman-Monteith,
[ADR-0004](0004-etp-fao-penman-monteith.md)) **dans l'App 2 uniquement**, à partir du
**rayonnement ARPEGE** (≤ ~4 j). Elle est **retirée de l'App 1** (D1). *Option
différée* : produit grille « ETP quotidienne » MF (J→J+3).

### D7 — Pictogrammes

- **App 1** : picto **MF** → table de correspondance **icônes MF (`pNN…`, variantes
  jour/nuit + « bis ») → OMM 4677**, rendu avec les **icônes yr** (forme découplée du
  fond, conservée d'ADR-0013).
- **App 2** : **aucun pictogramme**.
- Le **port MET Norway (ADR-0013)** n'est plus utilisé en primaire ; conservé dans le
  socle comme **repli** (App 1 si MF muet / queue) et utilitaire.

### D8 — Proba de pluie

- **App 1** : proba **MF calibrée** (`probability_forecast`).
- **App 2** : **proba d'ensemble ECMWF IFS-ENS conservée** (calcul socle transparent,
  ADR-0011). *(Pas d'abandon global de l'ensemble : seule l'App 1 ne l'utilise pas.)*

### D9 — Transparence assumée (dégradation par omission)

Prévi MF = source d'autorité opaque, non reproductible, accès non officiel. Mitigations :
**étiquetage honnête** (`updated_on`) ; **omission gracieuse** si l'endpoint est muet
(le mail/dashboard part sans le bloc — doctrine ADR-0011 D8) ; **token externalisé**
(secrets-agnostique) ; l'**App 2 transparente** (Single Runs + ETP) reste l'ossature
cross-checkable.

### D10 — Vigilance inchangée (seule autorité d'alerte)

La **Vigilance MF reste la seule méthode d'alerte** (orages/canicule…). Le picto MF
*illustre*, la Vigilance *alerte* → pas de doublon. Calée sur l'**heure légale FR**
(6 h / 16 h locales). Le cron matin **6 h 30 locale** laisse **~30 min de marge** sur
la Vigilance du matin (marge minimale assumée ; l'après-midi est large).

**Vérification de fraîcheur.** La source DPVigilance fournit `product.update_time`
(heure d'émission officielle de la carte, **en UTC** ; déjà extraite dans
`VigilanceDepartement.update_time`). On l'**affiche** (« Vigilance Météo-France, carte
du {update_time} », rendue en heure locale) **et** on **flague la péremption par
l'âge** : la carte étant publiée ≥ 2×/jour, une carte fraîche est récente → si
`now − update_time > 12 h`, on annote « actualisation pas encore publiée ». Le critère
porte sur l'**âge** (deux instants absolus) → insensible à l'ambiguïté de fuseau du
libellé MF. **Pas de retry runtime** : si la péremption à 6 h 30 devient systématique,
on **retarde le cron** (corriger la constante, doctrine ADR-0011 D4), on ne boucle pas.

## Conséquences

- **Socle** : nouvelle source `meteofrance_officiel` (1 JSON au point ; mapping
  picto→OMM ; proba ré-étalée/agrégée ; parsing `rain` à clés variables + `null` ;
  agrégation 6 h — pluie = somme, proba = max, T = min/max, picto = icône la plus
  significative ; **gestion heure locale**). `OpenMeteoSingleRuns` **conservé** (App 2),
  **réduit à ARPEGE + ECMWF + proba d'ensemble** ; **AROME retiré** de l'usage apps.
  Port MET Norway → repli.
- **App 1** : fetch MF seul ; **tout en heure locale** ; cron 6 h 30 / 18 h 30 local ;
  périodes 6 h (nuit/matin/après-midi/soir) ; horizon adaptatif (dernière période 6 h
  pleine de l'horaire) ; labels « Prévision MF / MàJ » ; suppression ETP, table de runs,
  ancre, stitch.
- **App 2** : ARPEGE + ECMWF (UTC), **sans picto**, proba d'ensemble conservée ;
  horizon 10 j (ECMWF), bins 12 h jour/nuit ; ETP/bilan conservés (ARPEGE) ;
  **déploiement Streamlit Cloud inchangé** (toujours Open-Meteo, pas de GRIB).
- **ADR-0011** : périmètre → App 2. **ADR-0013** : déprécié en primaire (repli).
- **Tests** : replay offline des deux apps (JSON MF synthétique → pipeline, par mode
  matin/après-midi, en heure locale ; Single Runs ARPEGE+ECMWF ; unités socle ; plages —
  notamment **première et dernière période** couvertes).
- **Risque** : dépendance MF non officielle → omission gracieuse + App 2 transparente.

## Alternatives écartées

- **MF-direct GRIB** : pas de WWMF ; accès lourd (pas d'endpoint point ; eccodes peu
  déployable). Réserve si Open-Meteo **et** le webservice MF ferment.
- **Tout sur la prévi MF (y compris App 2)** : perd le spread multi-modèle et la
  reproductibilité, cœur de l'App 2.
- **Garder une ligne de référence MF dans l'App 2** (cohérence e-mail ↔ dashboard) :
  écartée au profit d'un partage net (deux outils distincts) ; reconsidérable si la
  divergence e-mail/dashboard pose problème à l'usage.
- **Garder AROME dans l'App 2** : redondant avec la Veille MF en 0-48 h ; l'App 2 vise
  le spread/tendance (ARPEGE court + ECMWF long).
- **Picto fabriqué + orage CAPE pour l'App 1** : orage non validé, doublon Vigilance.
- **Périodes Veille en UTC** : labels matin/soir décalés ~2 h du ressenti ; l'heure
  locale les rend honnêtes (l'App 2, elle, reste UTC car orientée modèles/runs).
