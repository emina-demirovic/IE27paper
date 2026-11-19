#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/mac-env.sh"

worker_python="$HOME/ie27-ml-env/bin/python"
if [[ ! -x "$worker_python" ]]; then
  echo 'The local .NET installation or ie27-ml-env Python environment is missing.' >&2
  exit 1
fi
export SSL_CERT_FILE="$("$worker_python" -m certifi)"

worker_id="${1:-mac-w1}"
coordinator_url="${2:-http://localhost:5031}"
echo "Starting $worker_id against coordinator $coordinator_url"
cd "$repo_root"
exec dotnet run --project src/Worker -- \
  "--Worker:Id=$worker_id" \
  "--Worker:CoordinatorBaseUrl=$coordinator_url" \
  "--Worker:Executor:PythonCommand=$worker_python"
