# ADR-0021 — Veille 48 h sur portail-api MF (AROME + PE-AROME + DPVigilance), sortie du webservice bloqué

Statut : **Accepté** (2026-06-15) · **v0 acté sans la proba PE-ARPEGE J2-4,5** (proba
0-48 h PE-AROME seule ; extension différée, cf. deferrals) · remplace le canal
_prévision_ de [ADR-0014](0014-prevision-officielle-mf-veille.md)
(webservice → portail-api) ; amende [ADR-0017](0017-proba-semaine-mf-calibree.md)
(source proba) ; **dé-déprécie** [ADR-0013](0013-temps-sensible-arome.md) (moteur picto
ravivé) ; prolonge [ADR-0018](0018-ecmwf-direct-opendata.md) (enrichissement ECMWF).

## Contexte

La partie **48 h** d'App 1 (picto orage WWMF + proba calibrée + T/HR/vent/pluie) et
la **Vigilance** viennent du **webservice** `webservice.meteofrance.com` (ADR-0014).
Or ce backend **refuse l'IP datacenter des runners GitHub** : diagnostic du
2026-06-15 (`scripts/diag_mf_webservice.py`), **même token mobile → HTTP 200 en
résidentiel, 401 « you must provide a token » depuis le runner**, au même instant.
Ce n'est ni un token grillé (rotation inutile) ni notre clé DP (testée : `401
invalid token` sur le webservice). Conséquence vécue : le 2026-06-14 la 48 h a été
**omise** (commit #50, [feedback jamais-fausses-valeurs]). Alexis **n'a pas** de
machine maison 24/7 ; proxy résidentiel **exclu**. Le seul levier durable est de
**sortir du webservice**.

Diagnostic complémentaire (`diag_arome_capabilities.py`, `diag_dpvigilance_eps.py`,
`/tmp/probe_ecmwf.py`) : **tout `public-api.meteofrance.fr` (clé DP) et
`data.ecmwf.int` (sans clé) sont joignables depuis les runners** — comme ARPEGE
direct (ADR-0016) et ECMWF Open Data (ADR-0018) déjà en prod.

## Décision

Basculer **toute** la 48 h et la Vigilance d'App 1 sur `portail-api` (clé DP
`METEOFRANCE_DP_BASIC`) + ECMWF Open Data. **Plus aucun appel au webservice.**

1. **Champs prévision 48 h — AROME 0.025 direct.**
   `arome/1.0/wcs/MF-NWP-HIGHRES-AROME-0025-FRANCE-WCS` (92 familles, **diagnostics
   MF post-traités**, plus riche que AROME HD 0.01). On y prend T/HR/vent/pluie
   **et** les champs picto (cf. §2). Module socle nouveau `meteofrance_arome.py`,
   clone de `MeteoFranceArpege` (même OAuth, WCS, cache de run, unités socle).

2. **Picto — moteur unique dérivé, pour les 3 échéances.**
   On ravive `meteo_socle/indices/temps_sensible.py` (port MET Norway, ADR-0013) en
   **remplaçant ses proxies provisoires par les diagnostics MF** :
   - phase pluie/neige/**verglas** ← `PTYPE_60` (AROME) / `PRECIPITATION_TYPE_60_MIN`
     (ARPEGE) / `ptype` (ECMWF), au lieu de l'heuristique T° ;
   - brouillard ← `DIAG_BROUILL` / `VISIN_60` (AROME), au lieu du proxy HR ≥ 97 % ;
   - ciel ← nébulosité totale + couches ; averse vs continue ← convectif/large-scale
     (AROME/ARPEGE) ;
   - **branche orage-CAPE supprimée** (cf. §3).
   Le moteur prend **les champs présents** et dégrade proprement : ciel+pluie+**phase
   homogènes 0-10 j** (AROME 48 h, ARPEGE J0-4, ECMWF J4-10) ; brouillard et averse
   réservés à J0-4 (phénomènes de courte échéance). `_code_wmo` de `semaine.py` est
   **remplacé** par ce moteur (cohérence par construction). Vocabulaire d'icônes
   inchangé (yr / WMO 4677).

3. **Orage — Vigilance, jamais dérivé.**
   Le picto orage est **branché sur la Vigilance** (doctrine « une seule méthode /
   phénomène »), via **DPVigilance** : `DPVigilance/v1/cartevigilance/encours` (clé
   DP, joignable CI). Le produit « carte » expose **`periods` J/J+1 + `timelaps`
   horodatés** par phénomène et département → on **intersecte les tranches orages
   (dept 35) avec les fenêtres picto** → icône orage sur les fenêtres chevauchées,
   compatible matin/après-midi. Remplace `meteofrance_vigilance.py`
   (`currentphenomenons`, sur le webservice bloqué **et** trop grossier). Horizon
   Vigilance J/J+1 (~48 h) ; au-delà, pas d'orage (correct). Provenance
   **départementale**, à étiqueter.

4. **Proba pluie — PE-AROME pré-calculée, 0-48 h. Pas d'ECMWF-ENS.**
   `pearome/1.0/wcs/MF-NWP-HIGHRES-PEAROME-0025-FRANCE-WCS` n'expose pas de membres
   mais des **probabilités déjà calculées par MF** : `N_PROBA_PRECI06_*` =
   P(pluie > seuil mm / 6 h), `N_PROBA_PRECI12_*` (12 h). **Un champ, pas
   d'agrégation.** Couvre **0-48 h** (échéance PE-AROME ~51 h). Au-delà :
   - **ECMWF-ENS écarté** (décision : fetch trop lourd, ~40 Mo/membre-param-échéance) ;
   - **PEARP** (abonnement PE-ARPEGE, `pearpege/.../MF-NWP-GLOBAL-PEARP000-025-GLOBE-WCS`)
     ne sert que les **champs bruts** (T, TP, nébulosité, CAPE…), **pas de
     `N_PROBA`** pré-calculé. La proba PEARP pré-calculée est un **produit séparé**
     (« Champs statistiques de la prévision d'ensemble ARPEGE », id 297, à abonner) →
     extension **différée** pour J2-4,5 ; agréger les membres bruts = écarté (lourd) ;
   - **J5-10 : proba absente**, marquée (jamais de fausse valeur).
   Remplace la proba webservice d'ADR-0017 (calibrée mais sur le backend bloqué).

5. **Enrichissement ECMWF (ADR-0018).** Ajouter `ptype` (+ `sf`) à
   `_PARAMS_OPENDATA` → phase cohérente sur tout l'horizon.

## Conséquences

- **Robuste au blocage, zéro matériel maison** : tout sur clé DP / ECMWF, joignable
  depuis CI. La 48 h n'est plus omise.
- **On perd le statut « officiel » du picto** (dérivé, pas WWMF) — mais c'est la
  pratique standard (Open-Meteo dérive de même) et c'est documenté/transparent. On
  **gagne** le verglas (`PTYPE`) et un vrai brouillard (`DIAG_BROUILL`).
- **Proba = ensemble MF pré-calculé** (PE-AROME) au lieu de la proba point calibrée :
  méthode différente, à **valider sur 30 j vs doctrine** avant bascule
  (principe « vérifier les substitutions »). Couverture réduite à ~48 h en v0.
- **Vigilance robuste + horodatée** (bonus : matin/après-midi).
- **Doctrine préservée** : orage = Vigilance seule ; tous les calculs via le socle.
- App 1 reste « officielle » par la **Vigilance** et la prévi MF (AROME), même si le
  picto devient dérivé — la frontière App 1 (officiel) / App 2 (runs bruts) se
  **brouille** côté picto ; acté comme compromis fiabilité > officialité du symbole.

## À vérifier (deferrals v0, à lever par un `GetCoverage` réel)

- Valeurs numériques exactes de `PTYPE_60` (table GRIB 4.201 / locale MF) → mapping phase.
- Sémantique `N_PROBA_PRECI` (seuil en mm, valeur en %) et échéances exactes.
- Abonnement + route du produit « Champs statistiques PE-ARPEGE » (id 297) pour la
  proba pré-calculée J2-4,5 ; sinon proba absente au-delà de 48 h en v0.

## Plan d'implémentation (phasé, flags de staging comme ADR-0016/0018)

1. **Socle — sources** (offline-testable) :
   - `meteofrance_arome.py` (`MeteoFranceArome`, clone ARPEGE ; AROME 0.025 ; champs
     T/HR/vent/pluie + `PTYPE_60`, `DIAG_BROUILL`, `NEBUL`/couches, `VISIN_60`,
     `NEIGE`/`PRECSO`, `RR_SOL_GELE`).
   - `meteofrance_proba_arome.py` (PE-AROME `N_PROBA_PRECI06/12` → série proba/fenêtre).
   - `dpvigilance.py` (carte/encours → périodes orages horodatées dept 35), remplace
     `meteofrance_vigilance.py`.
   - `ecmwf_opendata.py` : + `ptype`, `sf`.
2. **Socle — picto** : dé-déprécier `temps_sensible.py` ; entrées = diagnostics MF
   (PTYPE/DIAG_BROUILL/convectif) ; retirer la branche orage-CAPE ; unifier
   `semaine._code_wmo` dessus.
3. **App** : 48 h ← AROME + PE-AROME + DPVigilance (retrait du chemin webservice
   `meteofrance_officiel`) ; overlay orage ← tranches DPVigilance ; semaine picto ←
   moteur unique (ARPEGE J0-4, ECMWF J4-10 + ptype).
4. **Tests** : intégration **offline** (prévi synthétique AROME/PE-AROME/DPVigilance
   → pipeline complet → mail), unités **en unités socle** (K, m/s, fraction) +
   assertions de plage sur la sortie affichée ; **tous les modes** (matin/après-midi,
   span = fetch réel) ; cas limites (run partiel, proba absente > 48 h, Vigilance
   absente, dept jaune sans tranche horaire).
5. **Validation avant bascule** : picto dérivé vs ancien picto MF sur une période ;
   proba PE-AROME vs doctrine (30 j) ; previews mail matin + après-midi
   (`/tmp/veille_preview_*.html`), rendu Posteo **et** Thunderbird.
6. **Bascule** : flags `source_meteo.{arome_mf_direct, proba_pearome, vigilance_dp}`
   OFF par défaut → ON après passage live. Retrait du webservice (et du workflow de
   diagnostic `diag-mf.yml`) une fois la bascule validée.
