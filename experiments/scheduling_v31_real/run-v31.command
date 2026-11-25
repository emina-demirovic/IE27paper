#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
source ../../scripts/danilos_mac/mac-env.sh
project="."
python_bin="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
dotnet build "$project/RealV31.csproj" --nologo -m:1 -p:NuGetAudit=false
clang -Wall -Wextra -Werror -O2 -dynamiclib "$project/cpu.c" -o "$project/bin/Debug/net10.0/libv31cpu.dylib"
exec "$python_bin" -Bu real_v31.py "$@"
