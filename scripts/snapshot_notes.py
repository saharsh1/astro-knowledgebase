#!/usr/bin/env python
"""Keep dated states of the notes (owner only). Notes in live/ are shared at once and are not
in git, so this is their history: one zip per snapshot in keeper/snapshots/, and a report of
what changed since the snapshot before.

    python scripts/snapshot_notes.py                 # take a snapshot (skipped if nothing changed)
    python scripts/snapshot_notes.py --list
    python scripts/snapshot_notes.py --restore notes-2026-11-13 [--note "<path in live/ or file name>"]

A snapshot is keeper/snapshots/notes-<date>.zip: every file of live/ under its path, plus
manifest.json (who, when, the checker's result, and per file its size, SHA-256, author and
title). A zip, not a folder: keeper/ is inside the Obsidian vault, and a folder of copies
would show every note twice. Generated notes (keeper/generated/) are not copied: they are
rebuilt from their sources.

The report, keeper/snapshots/notes-<date>-report.md, lists against the previous snapshot:
new, changed and deleted notes; notes whose `author` changed (one writer per note); Seafile
conflict copies; and review-marker hits in new or changed notes (rule 1), reviewed or not.

--restore writes into outbox/restored/<snapshot>/, never into live/: look at the files, then
/publish what should come back (or copy a file by hand if it replaces your own note).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kb_common import CONV, KEEPER, LIVE, OUTBOX, ROOT, frontmatter, github_user, today  # noqa: E402

SNAPS = KEEPER / "snapshots"


def snapshots() -> list[Path]:
    def key(p: Path):
        m = re.match(r"notes-(\d{4}-\d{2}-\d{2})(?:\.(\d+))?$", p.stem)
        return (m.group(1), int(m.group(2) or 1)) if m else ("", 0)
    return sorted((p for p in SNAPS.glob("notes-*.zip") if key(p)[0]), key=key) if SNAPS.exists() else []


def latest_name() -> str | None:
    s = snapshots()
    return s[-1].stem if s else None


def manifest_of(snap: Path) -> dict:
    with zipfile.ZipFile(snap) as z:
        return json.loads(z.read("manifest.json"))


def scan() -> dict[str, dict]:
    """path in live/ -> {size, sha256, author, title} for every file there (no hidden files)."""
    out = {}
    for f in sorted(LIVE.rglob("*")):
        rel = f.relative_to(LIVE)
        if not f.is_file() or any(part.startswith(".") for part in rel.parts):
            continue
        data = f.read_bytes()
        rec = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        if f.suffix == ".md":
            fm = frontmatter(f)
            rec["author"], rec["title"] = str(fm.get("author", "")), str(fm.get("title", ""))
            rec["markers_reviewed"] = bool(fm.get("markers_reviewed"))
        out[rel.as_posix()] = rec
    return out


def marker_hits(text: str) -> list[str]:
    hits = []
    for marker in CONV.get("review_markers", []):
        if (re.search(marker[3:], text) if marker.startswith("re:") else marker.lower() in text.lower()):
            hits.append(marker)
    return hits


def checker() -> str:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_vault.py")], cwd=ROOT, capture_output=True, text=True)
    return (r.stdout.strip().splitlines() or ["the checker gave no output"])[-1]


def report(name: str, now: dict, before: dict | None, prev_name: str | None, check: str, user: str) -> str:
    files, old = now, (before or {}).get("files", {})
    new = sorted(f for f in files if f not in old)
    gone = sorted(f for f in old if f not in files)
    changed = sorted(f for f in files if f in old and files[f]["sha256"] != old[f]["sha256"])
    authors = [(f, old[f].get("author", ""), files[f].get("author", "")) for f in changed
               if old[f].get("author", "") != files[f].get("author", "")]
    marker = CONV.get("conflict_marker", "SFConflict")
    conflicts = sorted(f for f in files if marker in f)
    hits = []
    for f in new + changed:
        if f.endswith(".md"):
            found = marker_hits((LIVE / f).read_text(encoding="utf-8", errors="replace"))
            if found:
                hits.append((f, found, files[f].get("markers_reviewed")))

    def who(f: str) -> str:
        a = files.get(f, old.get(f, {})).get("author", "")
        return f" ({a})" if a else ""

    def section(title: str, rows: list[str], none: str = "None.") -> list[str]:
        return [f"## {title} ({len(rows)})", "", *(rows or [none]), ""]
    lines = [f"# Notes snapshot {name}", "",
             f"> [!info] Written on {datetime.now().strftime('%Y-%m-%d %H:%M')} by `scripts/snapshot_notes.py` ({user}). "
             "Not written by an AI.", "",
             f"- **Compared with:** {prev_name or 'nothing (the first snapshot)'}",
             f"- **Files in live/:** {len(files)} ({sum(1 for f in files if f.endswith('.md'))} notes)",
             f"- **Checker:** {check}", ""]
    lines += section("Author changed: check the one-writer rule",
                     [f"- `{f}`: {a or '(none)'} → {b or '(none)'}" for f, a, b in authors])
    lines += section("Seafile conflict copies: run /resolve", [f"- `{f}`" for f in conflicts])
    lines += section("Review markers in new or changed notes (rule 1: no proprietary data)",
                     [f"- `{f}`{who(f)}: {', '.join(m)}" + (" — marked as reviewed" if r else " — **not reviewed**")
                      for f, m, r in hits])
    lines += section("New", [f"- `{f}`{who(f)}" for f in new])
    lines += section("Changed", [f"- `{f}`{who(f)}" for f in changed])
    lines += section("Deleted", [f"- `{f}`{who(f)}" for f in gone])
    return "\n".join(lines)


def take(force: bool) -> int:
    user = github_user()
    if user != CONV.get("owner"):
        sys.exit(f"Only the owner ({CONV.get('owner')}) takes snapshots; you are {user}.")
    if not LIVE.is_dir():
        sys.exit("live/ is missing: sync the Keeper library 'astro-kb-notes' first.")
    files = scan()
    prev = snapshots()
    before = manifest_of(prev[-1]) if prev else None
    same = before and {f: r["sha256"] for f, r in before["files"].items()} == {f: r["sha256"] for f, r in files.items()}
    if same and not force:
        print(f"Nothing changed since {prev[-1].stem}: no new snapshot (--force takes one anyway).")
        return 0
    SNAPS.mkdir(parents=True, exist_ok=True)
    name, n = f"notes-{today()}", 1
    while (SNAPS / f"{name}.zip").exists():
        n += 1
        name = f"notes-{today()}.{n}"
    check = checker()
    manifest = {"name": name, "taken": datetime.now().isoformat(timespec="seconds"), "by": user,
                "previous": prev[-1].stem if prev else None, "checker": check, "files": files}
    tmp = SNAPS / f"{name}.zip.writing"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(LIVE / rel, rel)
        z.writestr("manifest.json", json.dumps(manifest, indent=1, ensure_ascii=False))
    with zipfile.ZipFile(tmp) as z:                       # read it back before it counts
        bad = z.testzip()
        if bad or len(z.namelist()) != len(files) + 1:
            tmp.unlink()
            sys.exit(f"The snapshot did not read back correctly ({bad or 'file count'}): nothing was kept.")
    tmp.rename(SNAPS / f"{name}.zip")
    text = report(name, files, before, prev[-1].stem if prev else None, check, user)
    (SNAPS / f"{name}-report.md").write_text(text + "\n", encoding="utf-8")
    counts = {m.group(1): int(m.group(2)) for m in re.finditer(r"^## (\w+)[^\n(]*\((\d+)\)", text, re.M)}
    print(f"Snapshot {name}: {len(files)} files, {(SNAPS / (name + '.zip')).stat().st_size // 1024} kB. "
          f"New {counts.get('New', 0)}, changed {counts.get('Changed', 0)}, deleted {counts.get('Deleted', 0)}; "
          f"author changed {counts.get('Author', 0)}, conflict copies {counts.get('Seafile', 0)}, "
          f"marker hits {counts.get('Review', 0)}.")
    print(f"Report: keeper/snapshots/{name}-report.md")
    return 0


def show() -> int:
    snaps = snapshots()
    if not snaps:
        print("No snapshots yet.")
    for s in snaps:
        m = manifest_of(s)
        print(f"{s.stem:22s} {m['taken']}  {len(m['files']):5d} files  by {m['by']}  {m['checker']}")
    return 0


def restore(name: str, note: str | None) -> int:
    snap = SNAPS / f"{name.removesuffix('.zip')}.zip"
    if not snap.exists():
        sys.exit(f"No snapshot {name}. Have: {', '.join(s.stem for s in snapshots()) or 'none'}")
    dest = OUTBOX / "restored" / snap.stem
    with zipfile.ZipFile(snap) as z:
        names = [n for n in z.namelist() if n != "manifest.json"]
        if note:
            want = [n for n in names if n == note or Path(n).name == note or Path(n).stem == note]
            if not want:
                sys.exit(f"'{note}' is not in {snap.stem}.")
            names = want
        for n in names:
            target = (dest / n).resolve()
            if dest.resolve() not in target.parents:       # a path that would leave the folder
                sys.exit(f"Refusing the path {n} in {snap.stem}.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(n))
    print(f"Restored {len(names)} file(s) from {snap.stem} into {dest.relative_to(ROOT)}/ (live/ is untouched).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--list", action="store_true")
    g.add_argument("--restore", metavar="SNAPSHOT")
    ap.add_argument("--note", help="with --restore: one note (its path in live/, or its file name)")
    ap.add_argument("--force", action="store_true", help="take a snapshot even if nothing changed")
    a = ap.parse_args()
    if a.list:
        return show()
    if a.restore:
        return restore(a.restore, a.note)
    return take(a.force)


if __name__ == "__main__":
    sys.exit(main())
