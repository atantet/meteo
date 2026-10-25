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
cd "$(dirname "$(readlink -f "$0")")/.."

PY=/home/atantet/.conda/envs/meteo/bin/python

# Sous cron, aucun agent SSH dans l'environnement : la clé GitHub est protégée
# par phrase de passe et déverrouillée par l'agent du bureau (gcr), joignable
# tant que la session est ouverte.
export SSH_AUTH_SOCK="${SSH_AUTH_SOCK:-/run/user/$(id -u)/gcr/ssh}"

# Ne commiter que sur main : sinon les données atterrissent dans la branche de
# travail en cours (cas du 2026-10-25) et n'arrivent jamais sur GitHub.
branche=$(git rev-parse --abbrev-ref HEAD)
if [ "$branche" != "main" ]; then
    echo "=== $(date -u +%Y-%m-%dT%H:%MZ) branche courante = $branche (≠ main) — pipeline sauté, revenir sur main et relancer. ==="
    exit 1
fi

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
    git commit -m "chore(calibration): pipeline auto $(date -u +%Y-%m-%dT%H:%MZ)" \
        -- data/calibration/labels.csv data/calibration/dataset.csv
    echo "Commit créé."
fi

# Push (y compris un commit laissé en local par un run précédent sans réseau).
# Rebase d'abord : main distant avance aussi par les fusions de PR.
if ! git pull --rebase --autostash --quiet; then
    git rebase --abort 2>/dev/null || true
    echo "Pull --rebase échoué — push non tenté, à rattraper manuellement."
    exit 1
fi
if git push; then
    echo "Push OK."
else
    echo "Push échoué — à rattraper manuellement."
fi
