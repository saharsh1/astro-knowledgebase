#!/usr/bin/env python
"""Tests for scripts/check_public.py: the guard that keeps notes, data, tokens and private
addresses out of the public skeleton.

    python scripts/test_check_public.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILS: list[str] = []


def expect(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        print("     " + detail.strip().replace("\n", "\n     "))


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / "repo"
        (root / "scripts").mkdir(parents=True)
        shutil.copy(REPO / "scripts" / "check_public.py", root / "scripts")
        (root / "README.md").write_text("Contact: alice@example.org\nClone: git@github.com:o/r.git\n")
        (root / "scripts" / "tool.py").write_text("print('hello')\n")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)

        def check() -> tuple[int, str]:
            r = subprocess.run([sys.executable, str(root / "scripts/check_public.py"), "--staged"],
                               capture_output=True, text=True, cwd=root)
            return r.returncode, r.stdout + r.stderr

        code, out = check()
        expect("a clean skeleton passes (example.org and the GitHub SSH address are allowed)", code == 0, out)

        token = "ghp_" + "a" * 36
        bad = {
            "a note in live/": ("live/binary-stars/notes/N.md", "x", "never in git"),
            "the Keeper roles file": ("keeper/roles.yaml", "curators: [bob]", "never in git"),
            "a file outside the skeleton": ("notes/N.md", "x", "not part of the skeleton"),
            "a data file in scripts/": ("scripts/table.csv", "a,b", "these go to Keeper"),
            "a PDF in docs/": ("docs/paper.pdf", "%PDF", "these go to Keeper"),
            "Obsidian bookmarks (note titles)": (".obsidian/bookmarks.json", "{}", "not part of the skeleton"),
            "a GitHub token": ("scripts/leak.py", f"TOKEN = '{token}'", "a GitHub token"),
            "a private e-mail address": ("docs/who.md", "Write to bob" + "@institute.de", "an e-mail address"),
            "a file over 1 MB": ("docs/big.md", "x" * 1_100_000, "more than 1 MB"),
            "a sandbox notebook": ("scripts/sandbox/a.ipynb", "{}", "never in git"),
        }
        for name, (rel, text, needle) in bad.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
            subprocess.run(["git", "-C", str(root), "add", "-f", rel], check=True)
            code, out = check()
            expect(f"refuses: {name}", code == 1 and needle in out, out)
            subprocess.run(["git", "-C", str(root), "rm", "-q", "--cached", rel], check=True)
            f.unlink()

        code, out = check()
        expect("clean again", code == 0, out)

    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
