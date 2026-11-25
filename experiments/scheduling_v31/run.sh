#!/usr/bin/env bash
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
v2="$dir/../scheduling_v2"
source "$dir/../../scripts/danilos_mac/mac-env.sh"
export DOTNET_HOSTBUILDER__RELOADCONFIGONCHANGE=false
python_bin="${SCHED_V2_PYTHON:-$v2/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  echo "Select the frozen V2 Python environment using SCHED_V2_PYTHON or run V2 setup." >&2
  exit 1
fi
dotnet build "$v2/SchedulingV2.csproj" -m:1 --nologo -p:NuGetAudit=false
clang -Wall -Wextra -Werror -O2 -dynamiclib "$dir/cpu.c" -o "$v2/bin/Debug/net10.0/libv31cpu.dylib"
if [[ "${1:-}" == test ]]; then
  "$python_bin" "$dir/tests/test_native.py" -v
  dotnet build "$dir/tests/SchedulingV31.Tests.csproj" -m:1 --nologo -p:NuGetAudit=false
  exec dotnet "$dir/tests/bin/Debug/net10.0/SchedulingV31.Tests.dll"
fi
exec "$python_bin" "$dir/compare.py" "$@"
