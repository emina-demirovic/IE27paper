#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source ../../scripts/danilos_mac/mac-env.sh
# This is a fixed-configuration measurement, so no config file watcher is needed.
export DOTNET_HOSTBUILDER__RELOADCONFIGONCHANGE=false
dotnet build SchedulingV1.csproj -m:1 --nologo
exec dotnet bin/Debug/net10.0/SchedulingV1.dll "$@"
