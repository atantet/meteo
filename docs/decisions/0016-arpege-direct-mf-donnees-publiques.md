# ADR-0016 — ARPEGE en direct depuis MF Données Publiques (semaine)

## Statut

**Accepté** (2026-06-12). **Amende le périmètre d'[ADR-0011](0011-single-runs-api-runs-explicites.md)**
(Single Runs Open-Meteo) pour la **source ARPEGE de la semaine** : elle passe d'Open-Meteo
au **webservice WCS de Météo-France Données Publiques**. ECMWF (tendance longue 10 j) reste
sur Open-Meteo. Complète l'amendement réseau d'[ADR-0014](0014-prevision-officielle-mf-veille.md).

## Contexte

Open-Meteo *single-runs* s'est révélé avoir une **ingestion erratique des runs** : le run
ARPEGE 00Z du jour est parfois absent (HTTP 400 « model run not available ») alors que MF
l'a publié — d'où des sections semaine en bandeau « indisponible » à répétition (juin 2026).

Diagnostic réseau depuis les runners GitHub (2026-06-11) :

- `webservice.meteofrance.com` (prévi consumer 48 h + Vigilance) : **bloqué** par
  intermittence (timeout TCP datacenter↔MF) — traité par le repli 48 h + re-run d'ADR-0014.
- `public-api.meteofrance.fr` (**Données Publiques**, modèles ARPEGE/AROME) : **joignable et
  rapide** (~0,3 s), sert **tous** les runs sans trou.
- `data.ecmwf.int` (opendata) : joignable, sans clé.

Les API directes servent du **GRIB** (pas du JSON au point). MF autorise un sous-ensemble
spatial serveur (WCS `subset`), mais **une seule tranche 2D par requête** et applique un
**quota par minute** (les bursts le font sauter ; ~70 requêtes séquentielles passent).

## Décision

1. **Source ARPEGE de la semaine = MF Données Publiques en direct** (`meteo_socle.sources.`
   `meteofrance_arpege.MeteoFranceArpege`, WCS `MF-NWP-GLOBAL-ARPEGE-025-GLOBE-WCS`).
   ECMWF reste Open-Meteo. Bascule par flag `config/operationnelle.yaml` →
   `source_meteo.arpege_mf_direct` ; un échec MF retombe sur la cascade existante (repli ECMWF).
2. **Auth** : OAuth2 `client_credentials`. Le secret **`METEOFRANCE_DP_BASIC`** est
   l'identifiant **Basic** (`client_id:client_secret` base64), échangé contre un bearer (~1 h).
   (≠ webservice public ; cf. renommage depuis `METEOFRANCE_TOKEN`.)
3. **Débit** : `GetCoverage` sous-ensemblé à la maille la plus proche (~200 o/requête),
   **1 requête par (variable × échéance)** ≈ 500/run ≈ ~10 min, **cadencé ≤ 50/min** (limiteur
   + retry sur throttle) pour respecter le quota/minute.
4. **Cache de run** : parquet par (run, point) ; la semaine est **un produit 1×/jour** (run 00Z,
   cf. [ADR-0015](0015-fusion-app2-dans-mail-veille.md)) → le matin fetch, l'après-midi sert du
   cache (`actions/cache`, clé = jour UTC). Timeout du workflow Veille porté à 30 min.
5. **Unités socle** : le module sort les mêmes colonnes/conventions que `OpenMeteoSingleRuns`
   (`rayonnement_global` en J/m²/h, etc.). ARPEGE étant **horaire ≤ 48 h puis 3-horaire**, on
   **rééchantillonne en horaire** (interpolation des instantanées, accumulées réparties sur la
   fenêtre) pour que l'ETP socle (qui suppose des pas horaires) reste correcte.

## Conséquences

- **+** Plus de trous de runs ; backend joignable depuis les runners ; donnée MF de première
  main, fraîche, tous cycles.
- **−** ~10 min de fetch le matin (cadençage quota) ; dépendance `eccodes`/GRIB ; complexité
  (quota, cache, rééchantillonnage). Mitigé : cache (après-midi instantané), garde-fous
  (cascade ECMWF, bandeau, mail d'échec).
- **Validation** avant bascule (run commun 2026-06-12 00Z) : déficit hydrique 4 j **MF −21,2 vs
  OM −21,4 mm**, **guides actifs identiques** → mêmes décisions. Conforme à la règle « vérifier
  les substitutions ».
- **Non retenu pour l'instant** : ECMWF en direct (opendata, GRIB global lourd) — chantier
  séparé si la fiabilité Open-Meteo de la tendance longue se dégrade. La clé ECMWF Web API
  (archive MARS) reste disponible mais inutile pour l'opendata.
