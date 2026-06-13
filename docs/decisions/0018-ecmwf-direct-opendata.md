# ADR-0018 — ECMWF IFS HRES en direct depuis ECMWF Open Data (semaine)

Statut : **Accepté** · prolonge [ADR-0016](0016-arpege-direct-mf-donnees-publiques.md)
(même motivation, autre modèle) ; amende [ADR-0011](0011-single-runs-api-runs-explicites.md)
(source ECMWF).

## Contexte

La **ligne ECMWF déterministe** de la tendance semaine venait d'Open-Meteo Single
Runs. Comme pour ARPEGE (ADR-0016), l'ingestion Open-Meteo s'est révélée
**lacunaire** : mi-juin 2026, les **rafales** ECMWF sont servies en pointillé sur
la moyenne portée (couverture ~94 % sur 4 j ; trous le 16-18/06 → mercredi/jeudi
sans vent affiché). Diagnostic 2026-06-11 : `data.ecmwf.int` (ECMWF Open Data) est
joignable depuis les runners.

## Décision

La ligne ECMWF déterministe peut être servie **en direct depuis ECMWF Open Data**
(`src/meteo_socle/sources/ecmwf_opendata.py`, `EcmwfOpendata.obtenir_run`), activée
par le flag `config/operationnelle.yaml → source_meteo.ecmwf_opendata_direct`
(**OFF par défaut**, staging prudent comme ARPEGE).

Faits techniques :
- **Libre, sans clé** (CC-BY 4.0). Client `ecmwf-opendata` (pip) → **un seul
  téléchargement GRIB multi-échéances** par variable (pas d'OAuth ni de quota,
  contrairement au WCS MF) ; `cfgrib`/`eccodes` lisent, on extrait le **point le
  plus proche** (grille **−180..180** : passer la longitude telle quelle).
- HRES 00/12Z : **3-horaire ≤ 144 h puis 6-horaire ≤ 240 h** → rééchantillonnage
  horaire (helpers partagés avec le module ARPEGE). `tp`/`ssrd` **cumulés depuis
  le run** → dé-accumulation. HR dérivée du point de rosée `2d` (Magnus), vent
  d'`10u`/`10v`. Sortie en **unités socle**.
- **Cache de run** parquet (`actions/cache` clé jour UTC), comme ARPEGE.
- Indisponible → `EcmwfIndisponibleError` → **cascade** (df_ecmwf=None : tendance
  limitée à ARPEGE, ou bandeau si les deux manquent), avec **anomalie visible**.

## Conséquences

- **Corrige le trou de rafales à la source** : couverture 100 % (vs 94 % Open-Meteo).
- **Substitution validée** (run 12Z, 4 j, au point) : Tmax 28,3 vs 28,6 °C ;
  **ETP 19,3 vs 18,7 mm (Δ ~3 %, pas de red flag)** ; vent moyen 2,5 vs 2,6 m/s.
- Autonomie accrue vis-à-vis d'Open-Meteo (ARPEGE **et** ECMWF servis en direct).
- Flag OFF par défaut : activation après un passage live, comme ARPEGE (ADR-0016).
- La **proba** reste la proba calibrée MF (ADR-0017), indépendante du modèle.
