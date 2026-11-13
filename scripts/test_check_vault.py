#!/usr/bin/env python
"""Tests for scripts/check_vault.py and .claude/hooks/one_writer.py.

Builds a throwaway vault in a temporary folder (the skeleton plus sample notes in live/),
runs the checker and the hook on good and bad cases, and fails if a rule is not enforced.

    python scripts/test_check_vault.py
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


def note(path: Path, fm: str, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm.strip()}\n---\n{body}\n", encoding="utf-8")


def run(root: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(root / "scripts" / "check_vault.py"), *args],
                       capture_output=True, text=True, cwd=root)
    return r.returncode, r.stdout + r.stderr


def expect(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        if detail:
            print("     " + detail.replace("\n", "\n     "))


def skeleton(tmp: Path) -> Path:
    root = tmp / "vault"
    for item in ["conventions.yaml", "templates", "scripts/check_vault.py", ".claude/hooks"]:
        src = REPO / item
        dst = root / item
        dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if src.is_dir() else shutil.copy)(src, dst)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "github.user", "alice"], check=True)
    return root


def good_notes(root: Path) -> None:
    live = root / "live"
    for arm in ["gaia", "software", "binary-stars", "milky-way", "hot-stars"]:
        (live / arm / "notes").mkdir(parents=True, exist_ok=True)
    note(live / "gaia/lessons/2026-11-13 - carol - corr_vec order.md", """
title: corr_vec order
type: lesson
kind: pitfall
author: carol
created: 2026-11-13
last_checked: 2026-11-13
status: current
applies_to: ["dr3:nss_two_body_orbit.corr_vec"]
tags: [NSS, DataModel]
""", "From the documentation; see [[Gaia BH1 paper]] for a use.")
    note(live / "software/notes/orblet.md", """
title: orblet
type: code-card
author: erin
created: 2026-11-13
repo: orblet
verified_at: ac3eeb7590cd
tags: [CodeCard, NSS]
""", "Reads corr_vec in the order of [[2026-11-13 - carol - corr_vec order]].")
    note(live / "hot-stars/notes/Hot binaries.md", """
title: Hot binaries
type: note
author: dave
created: 2026-11-13
tags: [NSS, OBStars, OrbitFitting]
""", "Decode the covariance as in [[2026-11-13 - carol - corr_vec order]], or with [[orblet]].")
    note(live / "binary-stars/lessons/2026-11-13 - alice - Period unit.md", """
title: Period unit
type: lesson
kind: tip
author: alice
created: 2026-11-13
last_checked: 2026-11-13
status: current
applies_to: ["dr3:nss_two_body_orbit.period"]
arms: [milky-way]
tags: [NSS, Kinematics]
""", "See [[Gaia BH1 paper]].")
    note(live / "binary-stars/discussion/Period unit - 2026-11-13 1015 - bob.md", """
title: Period unit - 2026-11-13 1015 - bob
type: discussion
about: "[[2026-11-13 - alice - Period unit]]"
author: bob
created: 2026-11-13
tags: []
""", "Confirmed.")
    note(live / "binary-stars/topics/Topic - NSS units - alice - 2026-11-13.md", """
title: Topic - NSS units - alice - 2026-11-13
type: topic
author: alice
created: 2026-11-13
consolidates: ["[[2026-11-13 - alice - Period unit]]"]
tags: [NSS]
""")
    note(live / "papers/Gaia BH1 paper.md", """
title: Gaia BH1 paper
type: paper
author: alice
created: 2026-11-13
arxiv: "2209.06833"
bibcode: 2023MNRAS.518.1057E
bibtex: x
arms: [binary-stars]
tags: [Gaia]
""")
    note(live / "requests/2026-11-13 - bob - 2302.07880.md", """
title: 2026-11-13 - bob - 2302.07880
type: request
id: "2302.07880"
arm: binary-stars
reason: Gaia BH2
author: bob
created: 2026-11-13
tags: []
""")


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        root = skeleton(tmp)

        code, out = run(root)
        expect("skeleton only (no live/): passes", code == 0 and "skeleton only" in out, out)

        good_notes(root)
        code, out = run(root)
        expect("good notes in five arms (links run down the layers; lower layers' tags allowed): no errors", code == 0 and "0 error(s)" in out, out)

        live = root / "live"
        bad = {
            "author in file name differs from author": (
                live / "binary-stars/lessons/2026-11-13 - bob - Other.md",
                "title: Other\ntype: lesson\nkind: tip\nauthor: alice\ncreated: 2026-11-13\n"
                "last_checked: 2026-11-13\nstatus: current\napplies_to: []\ntags: []",
                "file name names 'bob'"),
            "Seafile conflict copy": (
                live / "papers/Gaia BH1 paper (SFConflict bob 2026-11-13-10-00-00).md",
                "title: x\ntype: paper\nauthor: bob\ncreated: 2026-11-13\ntags: []", "conflict copy"),
            "same file name in two arms": (
                live / "milky-way/notes/Gaia BH1 paper.md",
                "title: x\ntype: note\nauthor: bob\ncreated: 2026-11-13\ntags: []", "used more than once"),
            "tag of another arm": (
                live / "hot-stars/notes/Winds note.md",
                "title: Winds note\ntype: note\nauthor: bob\ncreated: 2026-11-13\ntags: [Orbits]",
                "tag 'Orbits' is not allowed"),
            "a gaia note links into a science arm": (
                live / "gaia/notes/Column use.md",
                "title: c\ntype: note\nauthor: bob\ncreated: 2026-11-13\ntags: []", "links run"),
            "a gaia note links into software": (
                live / "gaia/notes/Uses code.md",
                "title: u\ntype: note\nauthor: bob\ncreated: 2026-11-13\ntags: []", "links run"),
            "a software note links into a science arm": (
                live / "software/notes/Back link.md",
                "title: b\ntype: note\nauthor: bob\ncreated: 2026-11-13\ntags: []", "links run"),
            "a software note uses a science arm's tag": (
                live / "software/notes/Tagged.md",
                "title: t\ntype: note\nauthor: bob\ncreated: 2026-11-13\ntags: [Orbits]",
                "tag 'Orbits' is not allowed"),
            "a code card outside the software arm": (
                live / "binary-stars/notes/sedkit.md",
                "title: s\ntype: code-card\nauthor: bob\ncreated: 2026-11-13\nrepo: sedkit\n"
                "verified_at: x\ntags: []", "does not belong in binary-stars/notes"),
            "a gaia discussion is about a science note": (
                live / "gaia/discussion/Period unit - 2026-11-13 1200 - bob.md",
                "title: d\ntype: discussion\nabout: '[[2026-11-13 - alice - Period unit]]'\nauthor: bob\n"
                "created: 2026-11-13\ntags: []", "links run"),
            "about is not a wikilink": (
                live / "binary-stars/discussion/Period unit - 2026-11-13 1100 - carol.md",
                "title: d\ntype: discussion\nabout: Period unit\nauthor: carol\ncreated: 2026-11-13\ntags: []",
                "must hold wikilinks"),
            "lesson in the wrong place": (
                live / "papers/2026-11-13 - alice - Misplaced.md",
                "title: m\ntype: lesson\nkind: tip\nauthor: alice\ncreated: 2026-11-13\n"
                "last_checked: 2026-11-13\nstatus: current\napplies_to: []\ntags: []",
                "does not belong in papers"),
            "same bibcode twice": (
                live / "papers/Gaia BH1 again.md",
                "title: a\ntype: paper\nauthor: bob\ncreated: 2026-11-13\narxiv: '1'\n"
                "bibcode: 2023MNRAS.518.1057E\nbibtex: x\narms: [binary-stars]\ntags: []",
                "two paper notes have bibcode"),
            "unknown arm": (
                live / "milky-way/notes/Arms note.md",
                "title: a\ntype: note\nauthor: bob\ncreated: 2026-11-13\narms: [galaxies]\ntags: []",
                "arm 'galaxies' is not in"),
            "broken link": (
                live / "milky-way/notes/Link note.md",
                "title: l\ntype: note\nauthor: bob\ncreated: 2026-11-13\ntags: []", "does not resolve"),
        }
        for name, (path, fm, needle) in bad.items():
            body = {"broken link": "[[No such note]]",
                    "a gaia note links into a science arm": "Used in [[Hot binaries]].",
                    "a gaia note links into software": "Decoded by [[orblet]].",
                    "a software note links into a science arm": "Used in [[Hot binaries]]."}.get(name, "")
            note(path, fm, body)
            code, out = run(root)
            expect(f"catches: {name}", code == 1 and needle in out, out)
            path.unlink()

        code, out = run(root)
        expect("clean again after removing the bad notes", code == 0, out)

        draft = root / "outbox/new.md"
        note(draft, "title: n\ntype: note\nauthor: alice\ncreated: 2026-11-13\ntags: [Gaia]")
        code, out = run(root, "--draft", "outbox/new.md", "--dest", "live/milky-way/notes/New note.md")
        expect("--draft: a good draft passes", code == 0, out)
        code, out = run(root, "--draft", "outbox/new.md", "--dest", "live/papers/Gaia BH1 paper.md")
        expect("--draft: never overwrite an existing note", code == 1 and "exists already" in out, out)

        shutil.rmtree(live / "hot-stars")
        note(live / "milky-way/notes/To hot.md",
             "title: t\ntype: note\nauthor: bob\ncreated: 2026-11-13\ntags: []", "[[Only in hot-stars]]")
        code, out = run(root)
        expect("arm not synced: broken links are warnings", code == 0 and "an arm is not synced" in out, out)

        hook = root / ".claude/hooks/one_writer.py"

        def hook_says(path: str) -> int:
            r = subprocess.run([sys.executable, str(hook)], input=json.dumps(
                {"tool_name": "Edit", "tool_input": {"file_path": path}}), capture_output=True, text=True)
            return r.returncode

        lesson = "live/binary-stars/lessons/2026-11-13 - alice - Period unit.md"
        expect("hook: the author may edit her note", hook_says(str(root / lesson)) == 0)
        expect("hook: another member's note is blocked",
               hook_says(str(root / "live/binary-stars/discussion/Period unit - 2026-11-13 1015 - bob.md")) == 2)
        expect("hook: a new file in live/ is blocked", hook_says(str(root / "live/milky-way/notes/Brand new.md")) == 2)
        expect("hook: keeper/ is blocked", hook_says(str(root / "keeper/generated/Home.md")) == 2)
        expect("hook: outbox/ is allowed", hook_says(str(root / "outbox/draft.md")) == 0)

    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
