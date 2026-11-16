#!/usr/bin/env python
"""Bring this clone of the knowledge base up to date and say what is still behind.

  1. skeleton  git pull --ff-only on main (never with changes to tracked files; never on
               another branch); says when the rules or the Python environment changed;
  2. Keeper    keeper/ (astro-kb-data) and live/ (astro-kb-notes) present; every locked
               data file present with its size (--full: and its SHA-256); Seafile conflict
               copies in live/; drafts waiting in outbox/;
  3. code      the checkouts in external/ at the pins of sources.yaml (scripts/fetch_code.py
               for any that differ);
  4. index     copy a newer published index from keeper/index/ (publish_index.py --pull),
               then index what is newer than it here (python -m kb_pkg.index).

One line per step: OK, DONE (updated now), WARN (works, something is behind) or STOP (needs
the user). Nothing is pushed and nothing is deleted.

    python scripts/sync.py [--full] [--no-build] [--offline]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kb_common import CONV, KEEPER, LIVE, OUTBOX, ROOT  # noqa: E402

LINES: list[tuple[str, str, str]] = []


def say(level: str, what: str, detail: str = "") -> None:
    LINES.append((level, what, detail))
    print(f"{level:4s}  {what}" + (f": {detail}" if detail else ""), flush=True)


def git(*args: str, cwd: Path = ROOT) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.returncode, (r.stdout.strip() or r.stderr.strip())


def rules_version(rev: str) -> str:
    import yaml
    code, text = git("show", f"{rev}:conventions.yaml")
    return str(yaml.safe_load(text).get("version")) if code == 0 else "?"


def skeleton(offline: bool, apply: bool = True) -> None:
    _, branch = git("rev-parse", "--abbrev-ref", "HEAD")
    _, dirty = git("status", "--porcelain", "--untracked-files=no")
    _, remotes = git("remote")
    if "origin" not in remotes.split():
        say("WARN", "skeleton", "no remote 'origin' (the GitHub repository is not set up here): not pulled")
        return
    if offline:
        say("WARN", "skeleton", "not pulled (--offline)")
        return
    if branch != "main":
        say("STOP", "skeleton", f"on branch '{branch}', not main: share or finish that work, then "
                                "`git switch main` and sync again")
        return
    if dirty:
        n = len(dirty.splitlines())
        say("STOP", "skeleton", f"{n} tracked file(s) changed here: /share them or `git stash` first "
                                "(nothing was pulled)")
        return
    code, out = git("fetch", "-q", "origin", "main")
    if code:
        say("WARN", "skeleton", f"could not reach GitHub (offline?): {out[-200:]}")
        return
    _, behind = git("rev-list", "--count", "HEAD..origin/main")
    _, ahead = git("rev-list", "--count", "origin/main..HEAD")
    if ahead != "0":
        say("STOP", "skeleton", f"local main has {ahead} commit(s) that GitHub does not: move them to a "
                                "branch and /share them (main only changes through pull requests)")
        return
    if behind == "0":
        say("OK", "skeleton", "up to date with GitHub")
        return
    if not apply:
        v = rules_version("origin/main")
        say("WARN", "skeleton", f"{behind} commit(s) behind GitHub"
            + (f" (rules version {v} there, {rules_version('HEAD')} here)" if v != rules_version("HEAD") else "")
            + ": run /sync")
        return
    before = git("rev-parse", "HEAD")[1]
    code, out = git("merge", "--ff-only", "-q", "origin/main")
    if code:
        say("STOP", "skeleton", f"pull is not a fast-forward: {out[-300:]}")
        return
    old_v, new_v = rules_version(before), rules_version("HEAD")
    _, changed = git("diff", "--name-only", before, "HEAD")
    changed = changed.splitlines()
    say("DONE", "skeleton", f"pulled {behind} commit(s)" + (f"; the rules moved from version {old_v} to {new_v}: "
                                                          "read CLAUDE.md again" if old_v != new_v else ""))
    if any(f in changed for f in ("environment.yml", "scripts/kb_pkg/requirements.txt")):
        say("WARN", "Python environment", "environment.yml changed: update the environment "
                                          "(conda env update -f environment.yml)")


def keeper(full: bool) -> None:
    if not KEEPER.is_dir():
        say("STOP", "keeper/", "missing: sync the Keeper library 'astro-kb-data' into ./keeper with the Seafile client")
    else:
        missing = differ = 0
        locks = sorted((KEEPER / "locks").rglob("*.json")) if (KEEPER / "locks").exists() else []
        for lf in locks:
            try:
                lock = json.loads(lf.read_text())
            except ValueError:
                differ += 1
                continue
            f = KEEPER / lock["path"]
            if not f.exists():
                missing += 1
            elif f.stat().st_size != int(lock["size"]) or (
                    full and hashlib.sha256(f.read_bytes()).hexdigest() != lock["sha256"]):
                differ += 1
        if missing or differ:
            say("WARN", "keeper/", f"{missing} of {len(locks)} locked files missing, {differ} different: "
                                   "the Seafile client is probably still syncing; sync again later")
        else:
            say("OK", "keeper/", f"all {len(locks)} locked files present" + (" and identical" if full else " (sizes)"))
    if not LIVE.is_dir():
        say("STOP", "live/", "missing: sync the Keeper library 'astro-kb-notes' into ./live with the Seafile client")
    else:
        marker = CONV.get("conflict_marker", "SFConflict")
        conflicts = [p for p in LIVE.rglob("*") if marker in p.name]
        notes = sum(1 for p in LIVE.rglob("*.md") if p.parent != LIVE)     # the root holds Keeper's own files
        if conflicts:
            say("WARN", "live/", f"{notes} notes; {len(conflicts)} Seafile conflict cop(ies): run /resolve")
        else:
            say("OK", "live/", f"{notes} notes, no conflict copies")
    drafts = sorted(OUTBOX.rglob("*.md")) if OUTBOX.exists() else []
    if drafts:
        say("WARN", "outbox/", f"{len(drafts)} draft(s) not shared yet: /publish them when ready")


def code(offline: bool, apply: bool = True) -> None:
    import yaml
    repos = yaml.safe_load((ROOT / "sources.yaml").read_text())["repositories"]
    off = []
    for r in repos:
        d = ROOT / "external" / r["name"]
        head = git("rev-parse", "HEAD", cwd=d)[1] if (d / ".git").exists() else ""
        if not head.startswith(str(r["commit"])):
            off.append(r["name"])
    if not off:
        say("OK", "code", f"{len(repos)} checkout(s) at their pins")
        return
    if offline or not apply:
        say("WARN", "code", f"not at the pin: {', '.join(off)}: run /sync")
        return
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_code.py"), *off],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        say("WARN", "code", f"fetch_code.py failed for {', '.join(off)}: {(r.stderr or r.stdout).strip()[-300:]}")
    else:
        say("DONE", "code", f"checked out at the pin: {', '.join(off)}")


def index(build: bool, apply: bool = True) -> None:
    import publish_index as pi
    from kb_pkg import config, index as kb_index
    from kb_pkg.store import Store
    before = pi.meta_of(pi.LOCAL).get("version")
    published = pi.meta_of(pi.CURRENT)
    reported = False
    if not apply:
        if published and published.get("model_revision") != config.model_revision():
            say("FAIL", "published index", "made with another model revision than this clone's: run /sync")
            reported = True
        elif published and published.get("version") != before:
            say("WARN", "published index", f"version {published['version']} is published, "
                                           f"this machine has {before or 'its own build'}: run /sync")
            reported = True
        build = False
    else:
        try:
            pi.pull()
        except SystemExit as e:
            say("WARN", "published index", str(e))
            reported = True
    after = pi.meta_of(pi.LOCAL).get("version")
    if after != before:
        say("DONE", "published index", f"copied version {after}")
    elif reported:
        pass
    elif after:
        say("OK", "published index", f"local copy is version {after}")
    elif not (config.INDEX_DIR / "manifest.json").exists():
        say("WARN", "search index", "none here and none published: build one with "
                                    "`cd scripts && HF_HUB_OFFLINE=1 python -m kb_pkg.index` (about an hour)")
        return
    p = kb_index.pending(Store(config.INDEX_DIR))
    todo = {k: len(v) for k, v in p.items() if v}
    if not todo:
        say("OK", "search index", "matches the files here")
        return
    what = ", ".join(f"{n} {k}" for k, n in todo.items())
    if not build:
        say("WARN", "search index", f"{what}: run /sync (or cd scripts && HF_HUB_OFFLINE=1 python -m kb_pkg.index)")
        return
    env = {**os.environ, "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE", "1")}
    r = subprocess.run([sys.executable, "-W", "ignore", "-m", "kb_pkg.index"], cwd=ROOT / "scripts",
                       env=env, capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode:
        say("WARN", "search index", f"update failed: {(r.stderr or r.stdout).strip()[-300:]}")
    else:
        say("DONE", "search index", f"{what} → {last}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--full", action="store_true", help="also compare the SHA-256 of every Keeper file")
    ap.add_argument("--no-build", action="store_true", help="report what the index lacks, do not embed it")
    ap.add_argument("--offline", action="store_true", help="no GitHub: skip the pull and the code fetch")
    a = ap.parse_args()
    skeleton(a.offline)
    keeper(a.full)
    code(a.offline)
    index(not a.no_build)
    stops = sum(1 for l, _, _ in LINES if l == "STOP")
    warns = sum(1 for l, _, _ in LINES if l == "WARN")
    print(f"\n{len(LINES)} steps: {stops} STOP, {warns} WARN")
    return 1 if stops else 0


if __name__ == "__main__":
    sys.exit(main())
