#!/usr/bin/env python
"""Tests of scripts/share.py with a local stand-in for GitHub (a bare repository), no network:
- the status lists the changed files;
- a file that must not be public (data at the top level) stops the commit; nothing is
  committed, the branch is removed and the changes stay in the working tree;
- a good change is committed on <user>/<date>-<topic>, with the GitHub check's tests run;
- a second --commit on that branch adds to it;
- --push refuses main, pushes the branch, and gives the GitHub link for a github.com remote;
- notes, outbox and sandbox are never staged (git ignores them).

    python scripts/test_share.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILS: list[str] = []
SKELETON = [".claude", ".github", ".gitignore", "CLAUDE.md", "README.md", "conventions.yaml",
            "sources.yaml", "environment.yml", "scripts", "templates", "docs"]


def expect(name: str, ok: bool, detail="") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        print("     " + str(detail).strip().replace("\n", "\n     ")[:3000])


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def share(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / "scripts/share.py"), *args], cwd=root,
                          capture_output=True, text=True, env={**os.environ, "KB_NO_GH": "1"})


def main() -> int:
    sys.path.insert(0, str(REPO / "scripts"))
    import share as sh
    expect("GitHub links from ssh and https remotes",
           sh.compare_url("git@github.com:o/astro-knowledgebase.git", "u/b")
           == "https://github.com/o/astro-knowledgebase/compare/main...u/b?expand=1"
           and sh.compare_url("https://github.com/o/r", "x") == "https://github.com/o/r/compare/main...x?expand=1"
           and sh.compare_url("/tmp/origin.git", "x") is None)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        owner, origin, member = tmp / "owner", tmp / "origin.git", tmp / "member"
        owner.mkdir()
        for name in SKELETON:
            src = REPO / name
            if src.is_dir():
                shutil.copytree(src, owner / name, ignore=shutil.ignore_patterns("__pycache__"))
            elif src.exists():
                shutil.copy(src, owner / name)
        git(tmp, "init", "-q", "-b", "main", str(owner))
        git(owner, "config", "user.email", "t@example.org")
        git(owner, "config", "user.name", "t")
        git(owner, "add", "-A")
        git(owner, "commit", "-qm", "skeleton")
        git(tmp, "clone", "-q", "--bare", str(owner), str(origin))
        git(tmp, "clone", "-q", str(origin), str(member))
        for k, v in (("user.email", "m@example.org"), ("user.name", "m"), ("github.user", "member1")):
            git(member, "config", k, v)

        tpl = member / "templates" / "Lesson.md"
        tpl.write_text(tpl.read_text() + "\n<!-- a clearer hint -->\n")
        (member / "results.csv").write_text("a,b\n1,2\n")
        (member / "live/gaia/notes").mkdir(parents=True)
        (member / "live/gaia/notes/N.md").write_text("private")
        (member / "sandbox").mkdir()
        msg = member / "sandbox" / "msg.txt"
        msg.write_text("Clearer lesson template\n\nCo-Authored-By: test <noreply@example.org>\n")

        r = share(member)
        expect("the status lists the changed skeleton files, not notes or sandbox",
               "templates/Lesson.md" in r.stdout and "results.csv" in r.stdout
               and "live/" not in r.stdout and "sandbox" not in r.stdout, r.stdout + r.stderr)

        r = share(member, "--commit", "--topic", "Lesson template hint", "--message-file", str(msg))
        expect("a data file at the top level stops the commit",
               r.returncode == 1 and "Nothing was committed" in r.stdout and "results.csv" in r.stdout, r.stdout + r.stderr)
        expect("after a refusal: still on main, no new branch, changes kept, nothing staged",
               git(member, "rev-parse", "--abbrev-ref", "HEAD") == "main"
               and "member1/" not in git(member, "branch")
               and "clearer hint" in tpl.read_text() and git(member, "diff", "--cached", "--name-only") == "")
        (member / "results.csv").unlink()

        r = share(member, "--commit", "--topic", "Lesson template hint", "--message-file", str(msg))
        br = f"member1/{date.today().isoformat()}-lesson-template-hint"
        expect("a good change is committed on <user>/<date>-<topic> after the GitHub check's tests",
               r.returncode == 0 and git(member, "rev-parse", "--abbrev-ref", "HEAD") == br
               and "ok    scripts/test_check_vault.py" in r.stdout
               and git(member, "log", "-1", "--format=%s") == "Clearer lesson template", r.stdout + r.stderr)
        expect("the commit holds only the template",
               git(member, "show", "--name-only", "--format=", "HEAD") == "templates/Lesson.md")

        rd = member / "README.md"
        rd.write_text(rd.read_text() + "\nOne more line.\n")
        r = share(member, "--commit", "--topic", "ignored", "--message-file", str(msg), "README.md")
        expect("a second commit adds to the same branch",
               r.returncode == 0 and "adding to branch" in r.stdout and git(member, "rev-parse", "--abbrev-ref", "HEAD") == br
               and git(member, "rev-list", "--count", "main..HEAD") == "2", r.stdout + r.stderr)

        r = share(member, "--push")
        expect("--push pushes the branch to GitHub (the stand-in)",
               r.returncode == 0 and br in git(origin, "branch", "--list", br), r.stdout + r.stderr)
        expect("a remote that is not github.com gets no link", "open the pull request by hand" in r.stdout, r.stdout)
        git(member, "switch", "-q", "main")
        r = share(member, "--push")
        expect("--push refuses main", r.returncode != 0 and "Never push main" in r.stderr, r.stdout + r.stderr)
        expect("main on GitHub is unchanged", git(origin, "rev-list", "--count", "main") == "1")
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
