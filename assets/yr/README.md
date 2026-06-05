# Icônes météo — MET Norway (yr)

Icônes SVG du temps présent, issues du jeu **weathericons** de l'Institut
météorologique norvégien (MET Norway), utilisé sur yr.no.

- Source : <https://github.com/metno/weathericons>
- Licence : **MIT** (© 2015-2017 Yr) — cf. [`LICENSE`](LICENSE).
- Seul un sous-ensemble (variantes jour/nuit utiles) est vendu ici, mappé
  depuis les codes OMM 4677 par `apps/shared/pictograms.py`.

Choix cohérent avec l'algorithme de symbole temps de MET Norway porté dans le
socle (`src/meteo_socle/indices/temps_sensible.py`, cf. ADR-0013) : même
service météo national pour le **fond** (classification) et la **forme**
(icônes).

`not-available.png` est un fallback repris du jeu Meteocons (MIT) pour les
codes sans symbole.
