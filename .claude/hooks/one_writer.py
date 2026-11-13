#!/usr/bin/env python3
"""PreToolUse hook (Edit, Write, NotebookEdit): keep one writer per file.

- keeper/ (data, generated notes, locks): never written by hand. Blocked.
- live/: an existing note may be changed only by its author (frontmatter `author`,
  compared with `git config github.user`). A new file in live/ is blocked: drafts go to
  outbox/, and /publish moves them after the checks.
Exit 2 blocks the tool call and shows the message to Claude. Standard library only.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def block(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    raw = (data.get("tool_input") or {}).get("file_path") or (data.get("tool_input") or {}).get("notebook_path")
    if not raw:
        return
    path = Path(raw)
    path = (path if path.is_absolute() else ROOT / path).resolve()
    for name in ("keeper", "live"):
        base = (ROOT / name).resolve()
        if path == base or base in path.parents:
            break
    else:
        return
    if name == "keeper":
        block("keeper/ holds data, generated notes and locks: never edit them by hand "
              "(rule 4). Curators add files with /ingest; generated notes come from the scripts.")
    if not path.exists():
        block("Do not create notes directly in live/: anything there is shared at once. "
              "Write the draft in outbox/ and run /publish (rule 3).")
    user = subprocess.run(["git", "-C", str(ROOT), "config", "github.user"],
                          capture_output=True, text=True).stdout.strip()
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^author:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", text[:4000], re.M) if text.startswith("---") else None
    author = m.group(1).strip() if m else None
    if not user:
        block("Set your GitHub user name first: git config github.user <name>. "
              "Only a note's author may change it (rule 2).")
    if author != user:
        block(f"This note's author is '{author}', not '{user}'. Only the author changes a note "
              "(rule 2). Write a discussion file in outbox/ instead (templates/Discussion.md).")


if __name__ == "__main__":
    main()
