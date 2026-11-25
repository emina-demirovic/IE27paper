#!/bin/bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/../.." && pwd)"
scripts="$repo/src/Worker/Scripts"
python="$HOME/ie27-ml-env/bin/python"

"$python" -m pip install -r "$scripts/requirements-rl-discrete.txt"
for steps in 5000 25000; do
    "$python" "$scripts/run_experiment.py" \
        --experiment-id "cartpole-check-$steps" \
        --algorithm q-learning-discrete --environment cartpole \
        --seed 42 --max-steps "$steps"
done
echo "Obe CartPole konfiguracije su uspešno završene."
