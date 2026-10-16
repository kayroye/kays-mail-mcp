#!/usr/bin/env bash
# choose an available supported Python version before handing setup to the Python entry point
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# prefer the default interpreter and fall back through the supported minor versions
for candidate in python3 python3.14 python3.13 python3.12 python3.11; do
  if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3,11))'; then
    exec "$candidate" scripts/setup.py "$@"
  fi
done
printf '%s\n' 'Setup needs Python 3.11+. Install it and rerun ./setup.sh.' >&2
exit 1
