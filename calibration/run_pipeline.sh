#!/usr/bin/env bash
# Chaîne de calibration pictos : fetch_labels → collect → optimize → commit.
#
# Lancer juste après un run Veille (matin ou après-midi) depuis la machine locale.
# Le webservice MF (fetch_labels) est accessible en local seulement.
#
# Crontab locale recommandée (TZ=UTC pour coller aux runs Veille 04:30Z / 16:30Z) :
#   10 5  * * * TZ=UTC /home/atantet/projets/meteo/calibration/run_pipeline.sh >> /tmp/calib.log 2>&1
#   10 17 * * * TZ=UTC /home/atantet/projets/meteo/calibration/run_pipeline.sh >> /tmp/calib.log 2>&1
#
# En dehors de la crontab, lancer manuellement :
#   bash calibration/run_pipeline.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PY=/home/atantet/.conda/envs/meteo/bin/python

echo "=== $(date -u +%Y-%m-%dT%H:%MZ) fetch_labels ==="
"$PY" calibration/fetch_labels.py

echo "=== collect ==="
"$PY" calibration/collect.py

echo "=== optimize ==="
"$PY" calibration/optimize.py

# Commit si data/calibration/ a changé
if git diff --quiet data/calibration/; then
    echo "Pas de changement dans data/calibration/ — rien à commiter."
else
    git add data/calibration/labels.csv data/calibration/dataset.csv
    git commit -m "chore(calibration): pipeline auto $(date -u +%Y-%m-%dT%H:%MZ)"
    echo "Commit créé."
fi
