#!/usr/bin/env python
"""Tests of scripts/build/home.py on a synthetic vault (no network): Home, the papers and
lessons indexes and one page per arm; a paper cited by a science note is listed in that arm;
a pinned note is on Home; the owner's text above the marker is kept; the pages pass the
checker; bookmarks are written once and never replaced.

    python scripts/test_build_home.py
"""
from __future__ import annotations

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


PAPER = """---
title: "{stem}"
type: paper
created: 2026-11-13
author: owner
tags: [Gaia]
arms: [gaia]
arxiv: "2206.0000{n}"
bibtex: "x"
pdf: "{pdf}"
source_list: "ESA page (file.html): Processing papers"
paper_year: {year}
---
Text.
"""

LESSON = """---
title: Orbits need care
type: lesson
kind: pitfall
status: current
author: owner
created: 2026-11-14
last_checked: 2026-11-14
applies_to: ["dr3:nss_two_body_orbit.period"]
tags: [Gaia]
pinned: true
---
# Orbits need care

**What.** The period column is in days. A second sentence.

See [[Able et al (2023) - First paper]].
"""


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
        (root / "sources.yaml").write_text("repositories: []\ngaia:\n  - {label: DR3, status: formal, doc_version: '1.3'}\n")
        import yaml
        conv = yaml.safe_load((root / "conventions.yaml").read_text())
        for arm in conv["arms"]:
            for folder in conv["arm_folders"]:
                (root / "live" / arm / folder).mkdir(parents=True)
        (root / "live/papers").mkdir()
        (root / "keeper/generated/gaia").mkdir(parents=True)
        first, second = "Able et al (2023) - First paper", "Baker et al (2021) - Second paper"
        (root / "live/papers" / f"{first}.md").write_text(PAPER.format(stem=first, n=1, pdf="keeper/pdfs/a.pdf", year=2023))
        (root / "live/papers" / f"{second}.md").write_text(PAPER.format(stem=second, n=2, pdf="", year=2021))
        (root / "live/binary-stars/lessons/2026-11-14 - owner - Orbits need care.md").write_text(LESSON)
        (root / "live/binary-stars/notes/Digest - orbits.md").write_text(
            "---\ntitle: Digest - orbits\ntype: note\ncreated: 2026-11-15\nauthor: owner\ntags: [Gaia]\n---\nText.\n")
        (root / "keeper/generated/gaia/DR3 data model.md").write_text(
            "---\ntitle: DR3 data model\ntype: hub\ncreated: x\nauthor: g\ntags: [Gaia]\ngenerated: true\n---\nText.\n")

        def run(*args: str):
            return subprocess.run([sys.executable, str(root / "scripts/build/home.py"), *args], cwd=root,
                                  capture_output=True, text=True)
        r = run()
        gen = root / "keeper/generated"

        def read(rel: str) -> str:
            return (gen / rel).read_text() if (gen / rel).exists() else ""
        home, papers, lessons = read("Home.md"), read("Index - papers.md"), read("Index - lessons.md")
        arm = read("binary-stars/Arm - Binary stars.md")
        expect("Home, two indexes and a page per arm are written",
               r.returncode == 0 and home and papers and lessons and arm
               and all((gen / a / f"Arm - {s['title']}.md").exists() for a, s in conv["arms"].items()), r.stdout + r.stderr)
        expect("Home lists the arms with their counts, the newest lesson and the status",
               "[[Arm - Binary stars\\|Binary stars]] | 2 | 0 | 1 | 1 | 0 | 1 |" in home
               and "Orbits need care" in home and "[[DR3 data model]]" in home and "Gaia DR3: formal" in home, home)
        expect("a pinned note is on Home with its first sentence",
               "## 📌 Pinned" in home and "The period column is in days." in home and "second sentence" not in home, home)
        expect("a paper cited by a science note is listed in that arm, the other is not",
               first in arm and second not in arm and "## Papers (1)" in arm, arm)
        expect("the papers index groups by source list, newest first, and marks a missing PDF",
               "## Processing papers (2)" in papers and papers.index(first) < papers.index(second)
               and "Second paper (no PDF)" in papers and "*Gaia, Binary stars*" in papers, papers)
        expect("the lessons index lists the lesson under its status with its arm",
               "## Current (1)" in lessons and "*Binary stars*" in lessons and "dr3:nss_two_body_orbit.period" in lessons, lessons)
        c = subprocess.run([sys.executable, str(root / "scripts/check_vault.py")], cwd=root, capture_output=True, text=True)
        expect("the pages pass the checker", c.returncode == 0 and " 0 warning" in c.stdout, c.stdout + c.stderr)

        (gen / "Home.md").write_text(home.replace("<!-- home:start -->", "My own line.\n\n<!-- home:start -->", 1))
        (root / "live/binary-stars/lessons/2026-11-14 - owner - Orbits need care.md").unlink()
        run()
        home = read("Home.md")
        expect("the text above the marker is kept and the block is replaced",
               "My own line." in home and "Orbits need care" not in home and home.count("<!-- home:start -->") == 1, home)

        b = run("--bookmarks")
        marks = root / ".obsidian/bookmarks.json"
        expect("bookmarks name Home, the indexes and the arms",
               b.returncode == 0 and marks.exists() and "keeper/generated/Home.md" in marks.read_text()
               and "Arm - Hot stars.md" in marks.read_text(), b.stdout + b.stderr)
        marks.write_text("{\"items\": []}\n")
        run("--bookmarks")
        expect("existing bookmarks are never replaced", marks.read_text() == "{\"items\": []}\n", marks.read_text())
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
