#!/usr/bin/env bash
# Start the knowledge base's search server (MCP, stdio) for Claude Code.
# Python: KB_PYTHON from the environment, else the KB_PYTHON line of scripts/config.local
# (git-ignored, one per machine), else python3 on the PATH.
cd "$(dirname "$0")" || exit 1
if [ -z "$KB_PYTHON" ] && [ -f config.local ]; then
  KB_PYTHON=$(sed -n 's/^KB_PYTHON *= *//p' config.local | tr -d '"'"'" | head -1)
  KB_PYTHON=${KB_PYTHON/#\~/$HOME}
fi
export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1} PYTHONPATH="$PWD"
exec "${KB_PYTHON:-python3}" -W ignore -m kb_pkg.server
