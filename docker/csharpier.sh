#!/bin/sh

DIR="$(cd "$(dirname "$0")" && pwd)"

# Try to execute csharpier from the same directory as this script is located
# The binary may be named either dotnet-csharpier or csharpier
[ -x "${DIR}/dotnet-csharpier" ] && exec "${DIR}/dotnet-csharpier" "$@"
[ -x "${DIR}/csharpier" ] && exec "${DIR}/csharpier" "$@"

printf 'Error: csharpier not found\n' >&2
exit 1
