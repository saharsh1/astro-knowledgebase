#!/usr/bin/env python
"""Tests of scripts/snapshot_notes.py in a small vault:
- only the owner takes snapshots;
- the first snapshot holds every file of live/ and a manifest; hidden files are left out;
- with nothing changed, no second snapshot is taken;
- the report of the next snapshot lists new, changed and deleted notes, an author change,
  a conflict copy and a review marker in a changed note;
- --list shows the snapshots; --restore writes one note or all into outbox/, never into live/.

    python scripts/test_snapshot_notes.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILS: list[str] = []


def expect(name: str, ok: bool, detail="") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        print("     " + str(detail).strip().replace("\n", "\n     ")[:3000])


def note(root: Path, rel: str, author: str, body: str) -> None:
    p = root / "live" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    title = p.stem
    p.write_text(f"---\ntitle: {title}\ntype: note\ncreated: '2026-11-13'\nauthor: {author}\ntags: [Gaia]\n---\n# {title}\n\n{body}\n")


def main() -> int:
    import yaml
    owner = yaml.safe_load((REPO / "conventions.yaml").read_text())["owner"]
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / "vault"
        (root / "scripts").mkdir(parents=True)
        for s in ("kb_common.py", "check_vault.py", "snapshot_notes.py"):
            shutil.copy(REPO / "scripts" / s, root / "scripts")
        shutil.copytree(REPO / "templates", root / "templates")
        shutil.copy(REPO / "conventions.yaml", root)
        (root / "sources.yaml").write_text("repositories: []\ngaia: []\n")
        subprocess.run(["git", "init", "-q", str(root)], check=True)

        def run(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, str(root / "scripts/snapshot_notes.py"), *args], cwd=root,
                                  capture_output=True, text=True)

        def user(name: str) -> None:
            subprocess.run(["git", "-C", str(root), "config", "github.user", name], check=True)
        note(root, "gaia/notes/Zero point.md", "anna", "The parallax zero point.")
        note(root, "gaia/notes/RUWE.md", "ben", "RUWE above 1.4.")
        note(root, "gaia/notes/Old.md", "ben", "To be deleted.")
        (root / "live/.seafile-tmp").write_text("x")
        (root / "live/archive-metadata.md").write_text("Keeper puts this file in every library")
        snaps = root / "keeper/snapshots"

        user("member1")
        r = run()
        expect("a member cannot take a snapshot", r.returncode != 0 and "Only the owner" in r.stderr, r.stdout + r.stderr)
        user(owner)
        r = run()
        zips = sorted(snaps.glob("*.zip"))
        expect("the first snapshot is taken", r.returncode == 0 and len(zips) == 1, r.stdout + r.stderr)
        with zipfile.ZipFile(zips[0]) as z:
            names, man = set(z.namelist()), json.loads(z.read("manifest.json"))
        expect("it holds every note and a manifest, no hidden files and not Keeper's own files",
               names == {"gaia/notes/Zero point.md", "gaia/notes/RUWE.md", "gaia/notes/Old.md", "manifest.json"}, names)
        expect("the manifest records author and checksum", man["files"]["gaia/notes/RUWE.md"]["author"] == "ben"
               and len(man["files"]["gaia/notes/RUWE.md"]["sha256"]) == 64 and man["previous"] is None, man)
        first = zips[0].stem
        r = run()
        expect("nothing changed: no second snapshot", "Nothing changed" in r.stdout and len(list(snaps.glob("*.zip"))) == 1, r.stdout)

        note(root, "gaia/notes/Zero point.md", "carl", "The parallax zero point, from a DPAC internal note.")
        note(root, "gaia/notes/New one.md", "anna", "A new note.")
        (root / "live/gaia/notes/Old.md").unlink()
        (root / "live/gaia/notes/RUWE (SFConflict ben 2026-11-13).md").write_text("copy")
        r = run()
        zips = sorted(snaps.glob("*.zip"))
        second = [z for z in zips if z.stem != first][0].stem
        rep = (snaps / f"{second}-report.md").read_text()
        expect("the second snapshot is taken and named apart from the first", len(zips) == 2 and second != first, r.stdout + r.stderr)
        expect("the report lists the new, changed and deleted notes",
               "## New (2)" in rep and "`gaia/notes/New one.md` (anna)" in rep and "## Changed (1)" in rep
               and "## Deleted (1)" in rep and "`gaia/notes/Old.md`" in rep, rep)
        expect("the report shows the author change", "`gaia/notes/Zero point.md`: anna → carl" in rep, rep)
        expect("the report shows the conflict copy and points to /resolve", "RUWE (SFConflict" in rep and "/resolve" in rep, rep)
        expect("the report shows the review marker as not reviewed", "DPAC internal" in rep and "**not reviewed**" in rep, rep)

        r = run("--list")
        expect("--list shows both snapshots", first in r.stdout and second in r.stdout, r.stdout)
        r = run("--restore", first, "--note", "Old")
        got = root / "outbox/restored" / first / "gaia/notes/Old.md"
        expect("--restore --note brings one note back into outbox/", r.returncode == 0 and got.exists()
               and "To be deleted." in got.read_text() and not (root / "live/gaia/notes/Old.md").exists(), r.stdout + r.stderr)
        r = run("--restore", first)
        zp = root / "outbox/restored" / first / "gaia/notes/Zero point.md"
        expect("--restore brings back the earlier text of every note; live/ keeps the current text",
               zp.exists() and "DPAC" not in zp.read_text() and "DPAC" in (root / "live/gaia/notes/Zero point.md").read_text(), r.stdout + r.stderr)
        r = run("--restore", "notes-1999-01-01")
        expect("an unknown snapshot is refused", r.returncode != 0 and "No snapshot" in r.stderr, r.stderr)
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
