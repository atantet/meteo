# ADR-0011 — Prévision via Single Runs API (runs explicites, analyse vs prévision)

## Statut

**Proposé — note de cadrage, à discuter** (2026-06-04). Ne modifie pas encore
le code. Rouvre partiellement [ADR-0002](0002-sources-meteo-v0.md) (qui a acté
l'API *Forecast* d'Open-Meteo) **sans quitter Open-Meteo**.

## Contexte

Besoin déclencheur : pouvoir **mentionner dans le mail / le dashboard le run
de modèle réellement utilisé**, et distinguer honnêtement une **analyse**
(état initial T+0 d'un run) d'une **prévision** (T+h, h > 0).

Or l'API *Forecast* d'Open-Meteo (utilisée aujourd'hui par les deux apps)
**n'expose aucun run** : vérifié le 2026-06-04, la réponse ne contient que
`latitude, longitude, generationtime_ms, utc_offset, timezone, elevation,
hourly_units, hourly`. Aucun paramètre (`run`, `run_time`, `model_run`…) n'a
d'effet (400 ou ignoré). Elle **assemble les premières heures de runs
successifs** sans dire lesquels. Impossible donc d'étiqueter le run sans le
**fabriquer** (violerait le principe « pas de boîte noire »).

**Découverte** : Open-Meteo expose une **Single Runs API** distincte, dont le
paramètre `&run=<ISO sans secondes>` (aligné 00/06/12/18Z) sélectionne **un run
précis** — exactement comme on épingle déjà le run des cartes dans leur URL.
Vérifié sur la doc le 2026-06-04 :

- couvre `meteofrance_arome_france_hd`, `meteofrance_arpege_europe`,
  `ecmwf_ifs025` ;
- fournit `precipitation_probability` ; le rayonnement y est renommé
  **`shortwave_radiation_ghi`** ;
- **pas d'endpoint « dernier run »** → il faut tenter du plus récent au plus
  ancien et garder le premier qui répond (« runs not available return an
  error ») ;
- un run = série de **son init T+0 vers l'avant** (pas de passé avant l'init) ;
- archives depuis ~sept. 2025 (mars 2024 pour ECMWF IFS) — sans impact sur la
  climato (qui reste SAFRAN/ERA5, cf. ADR-0002).

Gain : run exact → **label « Source » véridique** + **T+0 = analyse / T+h =
prévision** exact (l'app 2 fait déjà cette distinction, mais en *approximé*).

## État actuel des deux apps (constat)

| Aspect | App 1 Veille | App 2 Opérationnelle |
|---|---|---|
| Modèles | Fusion **AROME + ARPEGE + ECMWF IFS** (1 appel, priorité) | **ARPEGE** (court 4 j) + **ECMWF IFS** (long 7 j), **appels séparés**, pas de fusion |
| Horizon | 48 h | 4 j (ARPEGE) / 7 j (ECMWF) |
| `past_days` | 1 (couvre 00 h → T+0 du jour) | 0 (guides) / 2 (courbes, cartes) |
| Ancrage fenêtre | demi-journée (00 h / 12 h locale) | `now` (UTC), pivot analyse/prévision à `now` |
| Analyse vs prévision | non (prévision seule) | **oui** — passé translucide « Analyse modèle » via `past_days` (T+0 des runs successifs, **pas ERA5** — déjà documenté honnêtement) vs futur opaque « Prévision » |
| Cartes + runs | 2 sources, runs explicites par moment (Met Office 00Z ; AROME 18Z-veille matin / 06Z-J après-midi) | 1 source ARPEGE-Eur, run via `_run_le_plus_recent` (latence 5 h + cycle 6 h + **fallback** run précédent) |
| Variables socle | T/HR/vent/pluie/proba/rayonnement → ETP FAO | idem + **mildiou Smith** + **bilan hydrique** complet |

Point notable : **trois logiques de sélection de run coexistent déjà** (Veille
cartes, Op `cartes_geo._run_le_plus_recent`, et le besoin nouveau côté
prévision) — candidates à une **factorisation socle**.

## Tensions à arbitrer (cœur de la discussion)

1. **Single Run (1 run, vers l'avant) vs affichage du passé.**
   L'app 2 montre **2 jours de passé** (« analyse modèle ») via `past_days`,
   qui assemble les T+0 de runs successifs. **Un seul Single Run ne couvre que
   de son init vers l'avant** → pour garder un passé *exact* il faudrait
   assembler les T+0 de ~8 runs (N appels Single Runs) = plus lourd. La Veille
   (snapshot avant-gardiste) s'accommode d'**un** run.
   → Op : hybride (`past_days` approx pour le passé + Single Run exact pour le
   futur) ? stitch multi-runs exact ? statu quo ?

2. **Cohérence des modèles.** Veille fusionne 3 modèles ; Op en utilise 2
   séparés par horizon. Sous Single Runs (1 run par appel **par modèle**), la
   fusion de Veille = N appels à fusionner. Faut-il une **stratégie modèle
   commune** aux deux apps (p.ex. AROME 0-2 j → ARPEGE 2-4 j → ECMWF 4-7 j) ?

3. **Helper de sélection de run unifié.** Factoriser dans le socle un unique
   « dernier run disponible, avec cascade/fallback » (latence + cycle 6 h),
   réutilisé par les 3 usages (prévision Veille, prévision Op, cartes).

4. **Ancrage de fenêtre.** Veille ancre sur la demi-journée (00 h/12 h), ce qui
   coïncide bien avec un init de run ; Op ancre sur `now`. À rendre cohérent
   avec l'init du run choisi.

5. **Latence par modèle.** AROME (Météociel ~7-9 h), ECMWF (open-data +2 h vs
   dissémination ~7-8 h) : la cascade de run doit être **par modèle**, pas
   globale.

## Conséquences pressenties

- Refactor du socle `OpenMeteoForecast` : nouvelle source/méthode ciblant la
  Single Runs API (paramètre `run`, cascade, renommage `shortwave_radiation_ghi`).
- Impacts : `apps/veille` (`__main__`, fenêtre `indicateurs`) **et**
  `apps/operationnelle` (3 fetchs `streamlit_app`, `series_temp`, `charts`,
  `indicateurs`). Jeux de tests *replay* à refaire.
- **Plus de requêtes** (par modèle × runs essayés) → cache obligatoire
  (rate-limit Open-Meteo, cf. ADR-0002). On a d'ailleurs été rate-limités en
  sondant le 2026-06-04.
- Gain : label Source véridique + analyse/prévision exacte (upgrade du
  « presque » actuel de l'app 2).
- Hors périmètre : climato/historique (restent SAFRAN/ERA5).

## Questions ouvertes (à trancher en discussion)

- **Q1 — modèles** : stratégie commune aux deux apps ? laquelle ?
- **Q2 — passé app 2** : hybride `past_days`+Single Run / stitch multi-runs
  exact / statu quo ?
- **Q3 — helper run socle** commun aux 3 usages : oui ?
- **Q4 — périmètre/séquencement** : les deux apps d'un coup, ou Veille en
  pilote puis Op ?
- **Q5 — ancrage** fenêtre cohérent entre apps ?
- **Q6 — repli** : garder l'API *Forecast* actuelle en secours si aucun run
  Single Runs ne répond ?

## Alternative écartée (pour mémoire)

**API Météo-France directe** (AROME/ARPEGE GRIB, run + échéance explicites) :
donnerait aussi le run exact, mais lourde (souscription, eccodes/cfgrib,
architecture hybride) — la Single Runs API atteint le même but en restant dans
Open-Meteo. Reste l'option ultime si Open-Meteo ferme (mitigation déjà prévue
en ADR-0002).
