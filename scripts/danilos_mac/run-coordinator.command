#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/mac-env.sh"
cd "$repo_root"
dotnet run --project src/Coordinator --no-launch-profile -- --urls "http://localhost:5031"
