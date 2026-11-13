#!/usr/bin/env python
"""Find and settle Seafile conflict copies in live/ (and keeper/), for /resolve.

When two machines change the same file between syncs, Seafile keeps one version and saves
the other next to it as "<name> (SFConflict <who> <when>).<ext>". Nothing merges them.

Usage:
    python scripts/resolve_conflicts.py                       # list the conflict copies
    python scripts/resolve_conflicts.py --show <copy>          # who, when, and the differences
    python scripts/resolve_conflicts.py --keep original <copy> # drop the copy
    python scripts/resolve_conflicts.py --keep copy <copy>     # the copy's text replaces the original

Rules:
- Only the note's author settles a conflict in it (one writer per file). For keeper/
  files, only the owner.
- A copy identical to its original holds nothing new: anyone may drop it.
- Nothing is deleted: a dropped file goes to .resolve-trash/<date>/ (local, git-ignored).
- To merge the two by hand: the author edits the original, then runs --keep original.
"""
from __future__ import annotations

import argparse
import difflib
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from kb_common import CONV, KEEPER, LIVE, ROOT, frontmatter, github_user

PATTERN = re.compile(r"^(?P<base>.+?) \(SFConflict (?P<who>[^ )]+) (?P<when>[^)]+)\)(?P<ext>\.[^.]*)?$")
TRASH = ROOT / ".resolve-trash"


def copies() -> list[Path]:
    out = []
    for base in (LIVE, KEEPER):
        if base.exists():
            out += sorted(p for p in base.rglob(f"*{CONV['conflict_marker']}*") if p.is_file())
    return out


def original_of(copy: Path) -> Path | None:
    m = PATTERN.match(copy.name)
    return copy.with_name(m.group("base") + (m.group("ext") or "")) if m else None


def owner_of(copy: Path, original: Path) -> str | None:
    """Who may settle it: the note's author (from the original, else the copy); keeper/: the owner."""
    if KEEPER.resolve() in copy.resolve().parents:
        return CONV.get("owner")
    for f in (original, copy):
        if f.exists() and f.suffix == ".md":
            a = frontmatter(f).get("author")
            if a:
                return str(a)
    return None


def same(a: Path, b: Path) -> bool:
    return a.exists() and b.exists() and a.read_bytes() == b.read_bytes()


def trash(p: Path) -> Path:
    dest = TRASH / datetime.now().strftime("%Y-%m-%d") / p.resolve().relative_to(ROOT.resolve())
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = dest.with_name(dest.stem + datetime.now().strftime("-%H%M%S") + dest.suffix)
    shutil.move(str(p), str(dest))
    return dest


def rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=Path)
    ap.add_argument("--keep", nargs=2, metavar=("original|copy", "COPY"))
    a = ap.parse_args()

    if a.show or a.keep:
        copy = (ROOT / (a.show or Path(a.keep[1]))).resolve()
        if not copy.exists() or CONV["conflict_marker"] not in copy.name:
            sys.exit(f"{copy} is not a conflict copy")
        original = original_of(copy)
        if original is None:
            sys.exit(f"cannot read the original's name from {copy.name}")
        m = PATTERN.match(copy.name)
        who = owner_of(copy, original)
        if a.show:
            print(f"copy:     {rel(copy)}\n          saved by {m.group('who')} at {m.group('when')}")
            print(f"original: {rel(original)}" + ("" if original.exists() else "  (missing)"))
            print(f"settled by: {who or 'unknown'} (the author)")
            if same(copy, original):
                print("\nThe two are identical: drop the copy (--keep original).")
            elif original.exists() and copy.suffix in (".md", ".txt", ".yaml", ".json", ".csv"):
                diff = difflib.unified_diff(original.read_text(errors="replace").splitlines(),
                                            copy.read_text(errors="replace").splitlines(),
                                            "original", "copy", lineterm="", n=2)
                print("\n" + "\n".join(diff))
            else:
                print(f"\nBinary or missing original: compare sizes {original.stat().st_size if original.exists() else '-'}"
                      f" vs {copy.stat().st_size} bytes.")
            return 0

        choice = a.keep[0]
        if choice not in ("original", "copy"):
            sys.exit("--keep takes 'original' or 'copy'")
        user = github_user()
        if not same(copy, original) and user != who:
            sys.exit(f"Only {who or 'the author'} settles this conflict (one writer per file). "
                     f"Tell them: {rel(copy)}")
        if choice == "original" or same(copy, original):
            print(f"dropped {rel(copy)} -> {rel(trash(copy))}")
        else:
            if original.exists():
                print(f"old original -> {rel(trash(original))}")
            shutil.move(str(copy), str(original))
            print(f"kept the copy's text as {rel(original)}")
        return 0

    found = copies()
    if not found:
        print("no conflict copies")
        return 0
    user = github_user()
    print(f"{len(found)} conflict copies:")
    for c in found:
        o = original_of(c)
        who = owner_of(c, o) if o else None
        state = ("identical: drop it" if o and same(c, o) else
                 "yours to settle" if who == user else f"for {who or 'the author'} to settle")
        print(f"  {rel(c)}\n     {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
