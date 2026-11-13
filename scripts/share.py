#!/usr/bin/env python
"""Propose a change to the skeleton (rules, scripts, templates, skills, pins, demos, docs)
as a pull request. Notes are not shared this way: they go to live/ with /publish.

    python scripts/share.py                                   # what would be shared, and checks
    python scripts/share.py --commit --topic "<few words>" --message-file <file> [paths ...]
    python scripts/share.py --push                            # push the branch, open the pull request

--commit, from main: makes the branch <github user>/<YYYY-MM-DD>-<topic> (the changes come
along), stages the paths (default: every changed file), runs the public-repository guard on
them, the checker and the tests the GitHub check runs (.github/workflows/check.yml), and
commits. When a check fails, nothing is committed and the clone is put back as it was.
From another branch it adds a commit to that branch (and to its open pull request).

--push pushes the branch (never main) and opens the pull request with `gh` when it is
installed and signed in; otherwise it prints the link that opens one on GitHub.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kb_common import ROOT, github_user  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "check.yml"


def git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (r.stdout.strip() or r.stderr.strip())


def branch() -> str:
    return git("rev-parse", "--abbrev-ref", "HEAD")[1]


def changes() -> list[tuple[str, str]]:
    """(status, path) of every changed or new file git would track."""
    out = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    rows, items = [], out.split("\0")
    i = 0
    while i < len(items):
        e = items[i]
        i += 1
        if len(e) < 4:
            continue
        st, path = e[:2], e[3:]
        if st[0] in "RC":                              # a rename: the old name follows; keep the new one
            i += 1
        rows.append((st.strip() or "?", path))
    return rows


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40].rstrip("-") or "change"


def ci_commands() -> list[list[str]]:
    """The `python scripts/...` steps of the GitHub check, run with this Python."""
    out = []
    for l in WORKFLOW.read_text().splitlines() if WORKFLOW.exists() else []:
        m = re.match(r"\s*-\s*run:\s*python\s+(scripts/\S+\.py)(.*)$", l)
        if m:
            out.append([sys.executable, m.group(1), *m.group(2).split()])
    return out


def run_checks() -> list[str]:
    """Run the guard on the staged files and the GitHub check's steps; return the failures.
    The checker looks at the skeleton only, as on GitHub: a note in live/ never blocks a
    change to the skeleton (/publish checks notes)."""
    fails = []
    for cmd in [[sys.executable, "scripts/check_public.py", "--staged"]] + \
               [c + (["--skeleton"] if c[1] == "scripts/check_vault.py" else [])
                for c in ci_commands() if c[1] != "scripts/check_public.py"]:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        name = " ".join(cmd[1:])
        print(("ok    " if r.returncode == 0 else "FAIL  ") + name, flush=True)
        if r.returncode:
            fails.append(f"{name}:\n{(r.stdout + r.stderr).strip()[-1500:]}")
    return fails


def compare_url(remote: str, br: str) -> str | None:
    m = re.match(r"(?:git@github\.com:|https://github\.com/)([^/]+/[^/]+?)(?:\.git)?/?$", remote)
    return f"https://github.com/{m.group(1)}/compare/main...{br}?expand=1" if m else None


def status() -> int:
    br, rows = branch(), changes()
    print(f"branch: {br}")
    if not rows:
        print("Nothing changed in the skeleton. (Notes are shared with /publish, not here.)")
        return 0
    for st, p in rows:
        print(f"  {st:2s} {p}")
    _, remotes = git("remote")
    if "origin" in remotes.split() and git("fetch", "-q", "origin", "main")[0] == 0:
        _, behind = git("rev-list", "--count", "HEAD..origin/main")
        if behind != "0":
            print(f"Note: GitHub's main has {behind} newer commit(s); the pull request may need them merged.")
    return 0


def commit(topic: str, message_file: Path, paths: list[str]) -> int:
    msg = message_file.read_text().strip() if message_file.exists() else ""
    if not msg:
        sys.exit(f"The commit message file {message_file} is missing or empty.")
    rows = changes()
    paths = paths or [p for _, p in rows]
    if not paths:
        sys.exit("Nothing to commit.")
    start, made = branch(), None
    if start == "main":
        made = f"{github_user()}/{date.today().isoformat()}-{slug(topic)}"
        if git("rev-parse", "--verify", "-q", f"refs/heads/{made}")[0] == 0:
            sys.exit(f"Branch {made} exists: choose another --topic, or switch to it and commit there.")
        code, out = git("switch", "-q", "-c", made)
        if code:
            sys.exit(out)
        print(f"branch {made} (from main)")
    else:
        print(f"adding to branch {start}")
    code, out = git("add", "--", *paths)
    fails = [f"git add: {out}"] if code else run_checks()
    if fails:
        git("reset", "-q", "--", *paths)               # unstage; the files keep their changes
        if made:
            git("switch", "-q", start)
            git("branch", "-q", "-D", made)
        print("\nNothing was committed; the clone is as it was.\n\n" + "\n\n".join(fails))
        return 1
    code, out = git("commit", "-q", "-F", str(message_file))
    if code:
        print(out)
        return 1
    print(f"\ncommitted {git('rev-parse', '--short', 'HEAD')[1]} on {branch()}. Next: python scripts/share.py --push")
    return 0


def push() -> int:
    br = branch()
    if br in ("main", "HEAD"):
        sys.exit("Never push main: commit on a branch first (--commit).")
    code, out = git("push", "-q", "-u", "origin", br)
    if code:
        print(f"push failed: {out}")
        return 1
    print(f"pushed {br}")
    gh = shutil.which("gh") if not os.environ.get("KB_NO_GH") else None
    if gh and subprocess.run([gh, "auth", "status"], capture_output=True).returncode == 0:
        r = subprocess.run([gh, "pr", "view", br, "--json", "url", "-q", ".url"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            print(f"the pull request is updated: {r.stdout.strip()}")
            return 0
        r = subprocess.run([gh, "pr", "create", "--base", "main", "--head", br, "--fill"],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            print(f"pull request: {r.stdout.strip().splitlines()[-1]}")
            return 0
        print(f"gh could not open the pull request: {r.stderr.strip()[-300:]}")
    url = compare_url(git("remote", "get-url", "origin")[1], br)
    print(f"open the pull request here: {url}" if url else "origin is not on GitHub: open the pull request by hand.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--commit", action="store_true")
    g.add_argument("--push", action="store_true")
    ap.add_argument("--topic", help="a few words: the branch name")
    ap.add_argument("--message-file", type=Path, help="the commit message")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args()
    if a.commit:
        if not (a.topic and a.message_file):
            ap.error("--commit needs --topic and --message-file")
        return commit(a.topic, a.message_file, a.paths)
    if a.push:
        return push()
    return status()


if __name__ == "__main__":
    sys.exit(main())
