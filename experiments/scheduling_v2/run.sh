#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "${1:-}" == setup ]]; then
  python3.11 -m venv .venv
  .venv/bin/python -m pip install --only-binary=:all: 'numpy==1.26.4' 'threadpoolctl==3.6.0'
  for p in 1 2 4; do
    .venv/bin/python matrix_job.py --algorithm numpy-dgemm --environment "128:$p" --seed 0 --max-steps 1
  done
  exit
fi
python_bin="${SCHED_V2_PYTHON:-$PWD/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  echo 'Run bash experiments/scheduling_v2/run.sh setup first (requires python3.11).' >&2
  exit 1
fi
if [[ "${1:-}" == test ]]; then
  exec "$python_bin" -m unittest -v test_scheduling
fi
if [[ "${1:-}" == smoke || "${1:-}" == full || "${1:-}" == control ]]; then
  source ../../scripts/danilos_mac/mac-env.sh
  export DOTNET_HOSTBUILDER__RELOADCONFIGONCHANGE=false
  dotnet build SchedulingV2.csproj -m:1 --nologo
fi
exec "$python_bin" experiment.py "$@"
