#!/usr/bin/env bash
set -euo pipefail

worker_count="${1:-}"
if [[ ! "$worker_count" =~ ^[1-9][0-9]*$ || ${#worker_count} -gt 4 || $# -gt 2 ]]; then
  echo "Usage: bash run-mac-workers.sh NUMBER_OF_WORKERS [COORDINATOR_URL]" >&2
  echo "Example: bash run-mac-workers.sh 4" >&2
  exit 1
fi

source "$(dirname "$0")/mac-env.sh"

worker_python="$HOME/ie27-ml-env/bin/python"
if [[ ! -x "$worker_python" ]]; then
  echo 'The local .NET installation or ie27-ml-env Python environment is missing.' >&2
  exit 1
fi
export SSL_CERT_FILE="$("$worker_python" -m certifi)"
coordinator_url="${2:-http://localhost:5031}"
echo "Coordinator: $coordinator_url"

# Build once before launching workers, avoiding concurrent builds.
cd "$repo_root"
dotnet build src/Worker --nologo
worker_dll="$PWD/src/Worker/bin/Debug/net10.0/Worker.dll"

# A distinct prefix prevents collisions with existing workers and other runs.
run_id="$(date +%Y%m%d-%H%M%S)-$$"
log_dir="$script_dir/worker-logs/$run_id"
mkdir -p "$log_dir"
worker_pids=()
cleanup() {
  trap - EXIT INT TERM
  if [[ ${#worker_pids[@]} -gt 0 ]]; then
    echo 'Stopping workers...'
    kill -TERM "${worker_pids[@]}" 2>/dev/null || true
    for worker_pid in "${worker_pids[@]}"; do
      wait "$worker_pid" 2>/dev/null || true
    done
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Use the project directory so the worker loads its appsettings.json.
cd src/Worker
for ((index = 1; index <= worker_count; index++)); do
  worker_id="mac-$run_id-w$index"
  dotnet "$worker_dll" \
    "--Worker:Id=$worker_id" \
    "--Worker:CoordinatorBaseUrl=$coordinator_url" \
    "--Worker:Executor:PythonCommand=$worker_python" \
    > "$log_dir/worker-$index.log" 2>&1 &
  worker_pids+=("$!")
  echo "Started $worker_id (PID $!)"
done

echo "Logs: $log_dir"
echo "Press Ctrl+C to stop all $worker_count workers started by this script."
while true; do
  for worker_pid in "${worker_pids[@]}"; do
    if ! kill -0 "$worker_pid" 2>/dev/null; then
      echo "Worker process $worker_pid exited. Check logs in $log_dir." >&2
      exit 1
    fi
  done
  sleep 1
done
