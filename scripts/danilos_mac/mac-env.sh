#!/usr/bin/env bash
# Shared environment for the launchers; source this file rather than running it.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
workspace_root="$(cd "$repo_root/.." && pwd)"
if [[ -x "$workspace_root/.dotnet/dotnet" ]]; then
  export DOTNET_ROOT="$workspace_root/.dotnet"
  export PATH="$DOTNET_ROOT:$PATH"
  export DOTNET_CLI_HOME="$workspace_root/.dotnet-home"
  export NUGET_PACKAGES="$workspace_root/.nuget/packages"
fi
export DOTNET_CLI_TELEMETRY_OPTOUT=1
if ! command -v dotnet >/dev/null 2>&1; then
  echo 'Install the .NET 10 SDK or provide ../.dotnet/dotnet beside the repository.' >&2
  exit 1
fi
