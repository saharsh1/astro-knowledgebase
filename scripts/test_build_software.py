#!/usr/bin/env python
"""Tests of scripts/build/code_usage.py and scripts/build/software_docs.py on a synthetic
repository (no network): Gaia columns found in strings and as table.column, a plain word
not taken for a column, the summary note with links to the data-model notes and to the
pinned lines, and the checker passing the note.

    python scripts/test_build_software.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILS: list[str] = []


def expect(name: str, ok: bool, detail="") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        print("     " + str(detail)[:3000])


CODE = '''"""Read Gaia orbits."""
import numpy as np


def load(t):
    """Load an orbit table."""
    query = "SELECT period, eccentricity FROM gaiadr3.nss_two_body_orbit"
    ruwe = t["ruwe"]            # Gaia gaia_source
    period = 3.0                # a local variable called period: not a column
    return t["nss_two_body_orbit.period"], ruwe, period
'''


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "vault"
        (root / "scripts").mkdir(parents=True)
        for s in ("kb_common.py", "check_vault.py"):
            shutil.copy(REPO / "scripts" / s, root / "scripts")
        shutil.copytree(REPO / "scripts/build", root / "scripts/build")
        shutil.copytree(REPO / "templates", root / "templates")
        shutil.copy(REPO / "conventions.yaml", root)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        ext = root / "external/fakecode"
        (ext / "src").mkdir(parents=True)
        (ext / "src/orbits.py").write_text(CODE)
        (ext / "README.md").write_text("# fakecode\n\nReads Gaia orbits.\n\n```\npip install fakecode\n\nmore\n```\n")
        (ext / "LICENSE").write_text("MIT License\n")
        for args in (["init", "-q"], ["add", "-A"], ["-c", "user.email=a@example.org", "-c", "user.name=a",
                                                    "commit", "-q", "-m", "x"]):
            subprocess.run(["git", "-C", str(ext), *args], check=True)
        sha = subprocess.run(["git", "-C", str(ext), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        (root / "sources.yaml").write_text(f"repositories:\n  - {{name: fakecode, url: https://github.com/x/fakecode, "
                                           f"commit: {sha[:12]}, index: [src, README.md]}}\n")
        p = root / "keeper/parsed/gaia/DR3"
        p.mkdir(parents=True)
        cols = [("nss_two_body_orbit", "period"), ("nss_two_body_orbit", "eccentricity"), ("gaia_source", "ruwe")]
        (p / "columns.jsonl").write_text("".join(json.dumps({"table": t, "column": c}) + "\n" for t, c in cols))
        (p / "tables.jsonl").write_text("".join(json.dumps({"table": t}) + "\n" for t in ("nss_two_body_orbit", "gaia_source")))
        g = root / "keeper/generated/gaia/DR3/datamodel"
        g.mkdir(parents=True)
        for t in ("nss_two_body_orbit", "gaia_source"):
            (g / f"DR3 - {t}.md").write_text(f"---\ntitle: DR3 - {t}\ntype: gaia-table\nauthor: g\ncreated: x\ntags: []\n"
                                             "release: DR3\ndoc_version: '1'\ngenerated: true\n---\n")

        r = subprocess.run([sys.executable, str(root / "scripts/build/code_usage.py")], cwd=root, capture_output=True, text=True)
        rows = {(x["table"], x["column"]): x["uses"] for x in map(json.loads, open(root / "keeper/parsed/usage/code.jsonl"))} \
            if r.returncode == 0 else {}
        expect("columns in strings and as table.column are found",
               ("nss_two_body_orbit", "period") in rows and ("gaia_source", "ruwe") in rows, r.stdout + r.stderr + str(rows))
        lines = {u["line"] for u in rows.get(("nss_two_body_orbit", "period"), [])}
        expect("a local variable called period is not taken for the column", 9 not in lines, lines)
        r = subprocess.run([sys.executable, str(root / "scripts/build/software_docs.py")], cwd=root, capture_output=True, text=True)
        note = root / "keeper/generated/software/Software - fakecode.md"
        text = note.read_text() if note.exists() else ""
        expect("the summary note links the column notes and the pinned lines",
               "[[DR3 - nss_two_body_orbit#period|nss_two_body_orbit.period]]" in text
               and f"https://github.com/x/fakecode/blob/{sha}/src/orbits.py#L" in text, r.stdout + r.stderr + text)
        expect("modules, licence and README are summarised",
               "`load`" in text and "Read Gaia orbits." in text and "MIT License" in text and "Reads Gaia orbits" in text, text)
        expect("a README excerpt never leaves a code block open", text.count("```") % 2 == 0, text)
        c = subprocess.run([sys.executable, str(root / "scripts/check_vault.py")], cwd=root, capture_output=True, text=True)
        expect("the summary note passes the checker", c.returncode == 0, c.stdout + c.stderr)
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
