# ADR-0011 — Prévision via Single Runs API (runs explicites et déterministes)

## Statut

**Accepté** (2026-06-04). Rouvre partiellement [ADR-0002](0002-sources-meteo-v0.md)
(qui actait l'API *Forecast* d'Open-Meteo) **sans quitter Open-Meteo** : on bascule
la **prévision** vers la **Single Runs API**, l'API *Forecast* étant **entièrement
retirée** (aucun repli). Hors périmètre : climato/historique (restent SAFRAN/ERA5).

## Contexte

Besoin déclencheur : **afficher honnêtement le run de modèle réellement utilisé**
(mail App 1 + dashboard App 2) et distinguer une **analyse** (état initial T+0 d'un
run) d'une **prévision** (T+h, h > 0).

L'API *Forecast* (utilisée jusqu'ici) **n'expose aucun run** : elle **assemble en
silence les premières heures de runs successifs** sans dire lesquels — la « boîte
noire » qu'on veut quitter (principe n°6). La **Single Runs API**
(`https://single-runs-api.open-meteo.com/v1/forecast`) sélectionne **un run précis**
via `&run=<ISO sans secondes>` (ex. `&run=2026-06-04T00:00`, aligné 00/06/12/18Z),
et renvoie **la série de ce seul run, de son init T+0 vers l'avant**.

### Faits vérifiés le 2026-06-04 (sonde directe — corrigent la note de cadrage initiale)

- **Endpoint** : `https://single-runs-api.open-meteo.com/v1/forecast`,
  `&run=<ISO sans secondes>`. Couvre `meteofrance_arome_france_hd`,
  `meteofrance_arpege_europe`, `ecmwf_ifs025`.
- **Le rayonnement n'est PAS renommé `shortwave_radiation_ghi`** (contrairement à ce
  qu'affirmait la note de cadrage) : ce nom est **rejeté (HTTP 400)**, de même que
  `global_horizontal_irradiance`. Le paramètre reconnu reste **`shortwave_radiation`**.
- **AROME France HD ne fournit ni rayonnement ni probabilité de pluie** en Single Runs
  (tous null sous tous les noms reconnus) — exactement comme en Forecast. **La fusion
  multi-modèles reste donc obligatoire** : un mono-modèle AROME est impossible.
- **La probabilité de pluie route en interne vers `ecmwf_ifs025_ensemble`** (modèle
  d'ensemble, à la disponibilité distincte et souvent en retard). C'est le **maillon
  le plus fragile** → premier candidat au mode dégradé.
- **Pas d'endpoint « dernier run »** : il faut désigner le run soi-même (d'où la
  sélection déterministe, D4). Archives depuis ~sept. 2025 (mars 2024 pour ECMWF IFS).
- **Rate-limit** sensible (on a été limités en sondant le 2026-06-04) → **cache
  obligatoire**.

## Décisions

### D1 — API & variables (Q1)

Bascule de la prévision sur la **Single Runs API**. Renommage `shortwave_radiation_ghi`
**écarté** (faux) : on garde `shortwave_radiation`. Fusion multi-modèles **maintenue**
(AROME seul insuffisant, vérifié).

### D2 — Modèles & fusion : option **B** (run le plus frais par modèle) (Q1)

- **App 1 (Veille)** : fusion par priorité **AROME** (cœur : T/HR/vent/pluie/temps)
  + **ARPEGE** (comble le rayonnement) + **ECMWF-ENS** (comble la proba). **Un appel
  par (modèle, run)**, **merge client-side par priorité** (remplace l'ancien
  `_fusionner_modeles` sur colonnes suffixées d'une réponse multi-modèles unique).
- **App 2 (Opérationnelle)** : **3 modèles** dans la grille tendance :
  - **AROME (Veille)** sur la **période commune 0-48 h** = **réutilise telle quelle la
    fusion App 1** (`OpenMeteoSingleRuns.obtenir_prevision`) → la ligne AROME du
    dashboard **coïncide exactement avec l'e-mail Veille** du même créneau (maille fine).
  - **ARPEGE** (court, 4 j ; pilote aussi guides + séries + bilan).
  - **ECMWF-HRES** (long, 7 j ; tendance). Chaque série porte son propre run.
  - L'App 2 **récupère ainsi la proba** (via la fusion AROME/ENS) qu'elle perdrait en
    HRES-seul, et les **deux produits ECMWF** y coexistent (ENS proba + HRES long).
- **Pas de cascade par horizon imposée** : chaque app garde sa composition (Veille
  fusionne, Op compare 3 modèles). La cohérence vient de l'infra commune (table de
  runs, fetch, merge) **et de la réutilisation de la fusion App 1 par l'App 2**.

### D3 — Cadence : créneaux **UTC fixes 12 h partagés** entre les 2 apps (Q1)

Deux créneaux UTC (= heures de cron App 1) : **matin ≥ 05:30 UTC**, **après-midi
≥ 17:30 UTC**. Dans un créneau, les runs sont **figés**. Table créneau→run unique
(source de vérité) :

| Clé de run | Matin (≥ 05:30 UTC) | Après-midi (≥ 17:30 UTC) |
|---|---|---|
| `AROME` *(App 1 + App 2 ligne AROME)* | 00Z J | 12Z J |
| `ARPEGE` *(App 1 + App 2 court)* | 00Z J | 12Z J |
| `ECMWF` — ENS proba *(App 1 + App 2 ligne AROME)* | 18Z J-1 | 06Z J |
| `ECMWF_HRES` — déterministe long *(App 2 long)* | **12Z J-1** | **00Z J** |

Règle : **Météo-France (AROME/ARPEGE) sur le run de la demi-journée courante ; ECMWF-ENS
un cran (6 h) derrière.** **ECMWF-HRES diffère** : la tendance App 2 va à 7 j, or les
runs ECMWF **06/18Z plafonnent à ~90 h** ; seuls les **00/12Z atteignent ~240 h**. On
prend donc le **dernier run long (00/12Z) publié** au créneau (12Z J-1 le matin, 00Z J
l'après-midi). ENS et HRES sont deux produits distincts du même modèle `ecmwf_ifs025` →
deux runs distincts, c'est normal. Socle : `creneau_run(now)` → (créneau, J) et
`runs_du_creneau(créneau, J)` → `{modèle: run}`. App 1 appelle à l'heure du cron,
App 2 au chargement → **le dashboard affiche toujours les runs de l'e-mail du même
créneau, par construction** (cohérence App 1 / App 2 garantie). Nuit (00:00-05:30
UTC) : on garde le créneau **après-midi de la veille** (pas de run nocturne auquel on
ne fait pas encore confiance).

### D4 — Sélection de run **déterministe, zéro itération** (Q3)

Pas de probe, pas de cascade « du plus récent au plus ancien », pas de fallback sur
le run précédent. La table D3 est calculable par
`run = floor((now − latence)/cycle)×cycle` avec latences **calibrables** (AROME ~4 h,
ARPEGE ~5 h, ECMWF-HRES ~8 h, ECMWF-ENS ~9 h ; cycle 6 h). **Si un run manque
systématiquement à l'heure dite, on corrige la constante** — pas de logique de
secours runtime. (Le `cartes_geo._run_le_plus_recent` perd son fallback 1-coup pour
s'aligner ; les cartes consomment la même logique déterministe.)

### D5 — Fenêtre & périodes : **tout en UTC, ancré sur l'init du run** (Q2)

- Fenêtre ancrée sur **l'init du run, en UTC** : App 1 `[init → +48 h]`, App 2
  `[init → horizon]`. **Plus de trou** (le début de fenêtre = le début du run).
  `ancre_fenetre` renvoie désormais l'init du run, pas « 00 h locale → UTC ».
- **App 1 — périodes = bins UTC** alignés sur les cycles de run :
  **Nuit 0-6 / Matin 6-12 / Après-midi 12-18 / Soir 18-24 UTC**. Noms FR conservés
  sur les bins UTC (défaut révisable ; ils décalent ~2 h du ressenti local — assumé,
  raisonner UTC est natif en météo). Affichage : chaque heure UTC est rendue/étiquetée
  en heure locale.
- **App 2 — grille tendance** : **Jour 06-18 UTC / Nuit 18-06 UTC** (12 h chacune).
  S'emboîte dans les quarts App 1 (Jour = Matin ∪ Après-midi ; Nuit = Soir ∪ Nuit
  suivante).

### D6 — Passé App 2 : **stitch déterministe de runs explicites** (Q2)

L'App 2 conserve ses **2 jours de passé** (contexte visuel « analyse modèle »), mais
**sans `past_days` Forecast** : on pave les 48 h de passé avec **les 4 créneaux-runs
précédents**, chacun tranché sur son segment de 12 h (T+0 → T+12 h). Exemple créneau
matin (run courant 00Z J) :

```
[00Z J-2 → 12Z J-2)   ← run 00Z J-2
[12Z J-2 → 00Z J-1)   ← run 12Z J-2
[00Z J-1 → 12Z J-1)   ← run 00Z J-1
[12Z J-1 → 00Z J  )   ← run 12Z J-1
[00Z J   → horizon ]  ← run 00Z J  (courant = prévision + badge)
```

Chaque segment porte **son run explicite** (provenance exacte y compris pour le passé).
Frontière passé/prévision = init du run courant (translucide « analyse » vs opaque
« prévision », pivot exact). **Conséquence : l'API Forecast quitte entièrement le
code** (plus aucun usage, même de secours — cf. D8). App 1 reste **sans passé**
(fenêtre = run courant) → pas de stitch côté App 1.

### D7 — Provenance **exacte par valeur**, jamais de run global mensonger (Q5)

On découple la **fenêtre d'affichage** (UX) de l'**init du run** (métadonnée), **mais**
chaque valeur affichée porte le run qui l'a produite. Interdiction d'un badge « run
unique » sur une série hétérogène. App 1 : comme AROME et ARPEGE coïncident (même run),
le badge se lit « run 00Z ; proba : run 18Z-veille ». App 2 : un run par série + labels
de segment distincts pour la bande passée.

### D8 — Donnée manquante : **on abandonne cette partie, aucun repli** (Q6)

**Pas de repli sur l'API Forecast** (ni run précédent, ni assemblage). Si un run
déterministe est muet / en erreur / rate-limité, on **omet la partie concernée** ; le
mail / le dashboard part quand même avec le reste (dégradation par **omission**, comme
déjà fait pour les cartes ou la Vigilance). Jamais d'affichage de données assemblées
en boîte noire. Granularité par contribution :

- proba ECMWF-ENS absente (cas le plus probable) → on omet la proba, le reste part ;
- rayonnement ARPEGE absent → pas d'ETP/bilan, mais T/pluie/vent restent ;
- AROME absent (rare, déterministe) → bloc prévision omis, le mail part avec
  Vigilance + cartes.

Si une omission devient **systématique** à l'heure dite → c'est le signal pour
corriger la constante de latence (D4), pas pour ajouter un secours runtime.
**Conséquence : l'API Forecast est retirée du code des apps** (elle ne survit que
comme alternative historique, cf. ADR-0002).

### D9 — Séquencement : **App 1 pilote, puis App 2** (Q4)

On construit et **valide offline** (test pipeline complet, prévision synthétique →
pipeline) le socle (`creneau_run`, `runs_du_creneau`, fetch Single Runs, merge
priorité, omission si run manquant) **sur l'App 1** d'abord — le badge « run » du mail est le
gain visible immédiat, et la table de runs est conçue autour de ses heures de cron.
L'App 2 réutilise ensuite ce socle + ajoute ses fetchs mono-modèle et le stitch passé
(D6).

## Conséquences

- **Socle `meteo_socle.sources`** : nouvelle source/méthode Single Runs (`run=`,
  `shortwave_radiation`) ; `creneau_run` / `runs_du_creneau` ; merge priorité sur
  N DataFrames ; omission par contribution si run manquant (pas de repli). Cache
  (runs passés immuables → TTL long ;
  run courant → rafraîchi par créneau). **Retrait du code de l'ancienne source
  Forecast** (`OpenMeteoForecast`/`past_days`) une fois les deux apps migrées.
- **App 1** : `__main__` (fetch = table runs + 3 appels + merge ; ancre = init run
  UTC ; plus de `past_days`), `indicateurs` (ancre UTC, périodes bins UTC 0-6/…/18-24),
  `email`/`charts` (badge run, périodes UTC), label « Source ».
- **App 2** : 3 fetchs → runs déterministes par créneau ; **stitch passé** (4 runs
  précédents × modèle, segments 12 h) ; grille jour/nuit UTC 06-18 / 18-06 ; badge run
  par série. `cartes_geo` : sélection déterministe (perd son fallback 1-coup).
- **Tests replay** à refaire (offline, pipeline complet) pour les deux apps.
- **Requêtes** : plus nombreuses (par modèle × runs), **mais** créneaux fixes +
  immutabilité des runs passés stabilisent le cache (≈ +1 run/modèle/créneau en régime
  établi). Cache obligatoire (rate-limit).

## Alternative écartée (pour mémoire)

**API Météo-France directe** (AROME/ARPEGE GRIB, run + échéance explicites) : donnerait
aussi le run exact, mais lourde (souscription, eccodes/cfgrib, architecture hybride).
La Single Runs API atteint le même but en restant dans Open-Meteo. Reste l'option
ultime si Open-Meteo ferme (mitigation déjà prévue en ADR-0002).
