#!/usr/bin/env bash
# Regenerate the software arm's generated notes from the pins in sources.yaml (index keeper,
# before /publish-index): code checkouts, Gaia columns found in the code, one summary note per
# repository. Ends with the checker. The Gaia arm (data model, documentation, papers) is built
# by hand when sources.yaml gains a release or a new documentation version: scripts/build/.
set -eu
cd "$(dirname "$0")/.."
PY=${KB_PYTHON:-}
if [ -z "$PY" ] && [ -f scripts/config.local ]; then
  PY=$(sed -n 's/^KB_PYTHON *= *//p' scripts/config.local | tr -d '"'"'" | head -1); PY=${PY/#\~/$HOME}
fi
PY=${PY:-python3}
"$PY" scripts/fetch_code.py
"$PY" scripts/build/code_usage.py
"$PY" scripts/build/software_docs.py
"$PY" scripts/build/home.py
"$PY" scripts/check_vault.py --keeper
