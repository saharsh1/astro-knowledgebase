#!/usr/bin/env bash
# One-time setup of the astro knowledge base on a machine. Safe to run again: every step
# checks first and skips what is done.
#
#   bash scripts/setup.sh                 # creates or updates the conda environment "bskb"
#   bash scripts/setup.sh --python PATH   # use an existing Python environment instead
#
# Before: clone this repository; in the Seafile app, sync the Keeper library "astro-kb-data"
# into ./keeper and "astro-kb-notes" into ./live ("sync with an existing folder").
# Needs: git, and conda (Miniforge) unless --python is given.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)
PY=""
if [ "${1:-}" = "--python" ]; then PY="${2:-}"; [ -x "$PY" ] || { echo "--python: $PY is not an executable"; exit 1; }; fi
step() { printf '\n== %s\n' "$*"; }

step "1. Python environment"
if [ -z "$PY" ]; then
  command -v conda >/dev/null 2>&1 || { echo "conda not found: install Miniforge (https://conda-forge.org/download/), then run this again."; exit 1; }
  if conda env list | awk '{print $1}' | grep -qx bskb; then
    echo "environment bskb exists: updating it from environment.yml"
    conda env update -n bskb -f environment.yml --prune || exit 1
  else
    conda env create -f environment.yml || exit 1
  fi
  PY="$(conda env list | awk '$1=="bskb" {print $NF}')/bin/python"
fi
"$PY" -c "import yaml, bs4, lancedb, sentence_transformers, pymupdf, mcp" 2>/dev/null \
  || { echo "packages missing in $PY: conda env update -n bskb -f environment.yml"; exit 1; }
echo "Python: $PY"

step "2. Local settings: scripts/config.local (not in git, not synced)"
# Only the KB_PYTHON line is written; other lines (tokens) are kept and never printed.
"$PY" - "$PY" <<'EOF'
import os, sys
from pathlib import Path
f, py = Path("scripts/config.local"), sys.argv[1]
lines = f.read_text().splitlines() if f.exists() else [
    "# Settings of this machine (git-ignored). Never share this file.",
    "# SCIX_TOKEN = \"...\"   # your own SciX/ADS token: only curators who ingest papers need it"]
new = f'KB_PYTHON = "{py}"'
old = [l for l in lines if l.strip().startswith("KB_PYTHON")]
lines = [new] + [l for l in lines if not l.strip().startswith("KB_PYTHON")]
f.write_text("\n".join(lines) + "\n")
os.chmod(f, 0o600)
print("KB_PYTHON " + ("unchanged" if old == [new] else "set") + "; scripts/config.local is readable by you only")
EOF

step "3. Git: your GitHub name and the pre-commit check"
if [ -z "$(git config github.user)" ]; then
  if [ -t 0 ]; then read -r -p "Your GitHub user name: " GH; [ -n "$GH" ] && git config github.user "$GH"; fi
fi
echo "github.user = $(git config github.user || true)"
[ -n "$(git config github.user)" ] || echo "Not set: git config github.user <name> (notes, branches and locks carry it)"
HOOK=.git/hooks/pre-commit
if [ -f "$HOOK" ] && ! grep -q "astro-kb pre-commit" "$HOOK"; then
  echo "$HOOK exists and is not ours: left as it is (the doctor will say the check is missing)"
else
  cat > "$HOOK" <<EOF
#!/usr/bin/env bash
# astro-kb pre-commit: nothing private reaches the public repository (scripts/setup.sh)
"$PY" scripts/check_public.py --staged && "$PY" scripts/check_vault.py --skeleton
EOF
  chmod +x "$HOOK"
  echo "pre-commit check installed"
fi

step "4. Search model (about 1.3 GB, once per machine; the revision is pinned)"
PYTHONPATH=scripts "$PY" -W ignore - <<'EOF'
from huggingface_hub import snapshot_download
from kb_pkg import config
model, rev = config.embedding_model(), config.model_revision()
try:
    snapshot_download(model, revision=rev, local_files_only=True)
    print(f"{model} at {rev[:10]}: already here")
except Exception:
    print(f"downloading {model} at {rev[:10]} ...")
    snapshot_download(model, revision=rev)     # fails if HF_HUB_OFFLINE=1 is set: unset it for this step
    print("downloaded")
EOF

step "5. Keeper libraries"
[ -d keeper ] || echo "keeper/ is missing: in the Seafile app, sync 'astro-kb-data' into $ROOT/keeper"
[ -d live ]   || echo "live/ is missing: in the Seafile app, sync 'astro-kb-notes' into $ROOT/live"
[ -d keeper ] && [ -d live ] && echo "both synced here"

step "6. Code, published index and anything newer (the /sync steps)"
"$PY" scripts/sync.py

step "7. Obsidian bookmarks (Home, the papers and lessons indexes, the arms)"
"$PY" scripts/build/home.py --bookmarks

step "8. Check"
"$PY" scripts/doctor.py
echo
echo "Next: open this folder in Obsidian and in Claude Code; approve the 'astro-kb' search server once."
