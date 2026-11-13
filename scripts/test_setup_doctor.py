#!/usr/bin/env python
"""Tests of scripts/setup.sh and scripts/doctor.py in a fresh clone of the skeleton, with the
Python of this environment (--python; no conda, no network: the search model must already
be in this machine's cache, as it is after one setup):
- setup writes scripts/config.local with KB_PYTHON, readable by the owner only;
- run again, it keeps the other lines of config.local (a token) and says KB_PYTHON is unchanged;
- setup installs the pre-commit check, and leaves a pre-commit hook that is not its own;
- without the Keeper libraries, setup says which library to sync where, and the doctor fails;
- the doctor reports a KB_PYTHON that does not exist, a config.local readable by others,
  a missing github.user;
- the doctor never prints the other lines of config.local.
Needs the knowledge base's environment.

    python scripts/test_setup_doctor.py
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILS: list[str] = []
SKELETON = [".claude", ".github", ".gitignore", ".mcp.json", "CLAUDE.md", "README.md", "conventions.yaml",
            "sources.yaml", "environment.yml", "scripts", "templates", "docs"]
SECRET = 'SCIX_TOKEN = "not-a-real-token-123"'


def expect(name: str, ok: bool, detail="") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        print("     " + str(detail).strip().replace("\n", "\n     ")[-3000:])


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True).stdout.strip()


def lines_of(out: str) -> dict[str, str]:
    d = {}
    for l in out.splitlines():
        if l[:4].strip() in ("OK", "DONE", "WARN", "STOP", "FAIL") and "  " in l:
            d[l[6:].split(":")[0]] = l
    return d


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / "clone"
        root.mkdir()
        for name in SKELETON:
            src = REPO / name
            if src.is_dir():
                shutil.copytree(src, root / name, ignore=shutil.ignore_patterns("__pycache__", "config.local"))
            elif src.exists():
                shutil.copy(src, root / name)
        (root / "sources.yaml").write_text("repositories: []\ngaia: []\n")
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
        git(root, "config", "github.user", "member1")
        env = {k: v for k, v in os.environ.items() if k != "KB_PYTHON"}

        def setup() -> subprocess.CompletedProcess:
            return subprocess.run(["bash", "scripts/setup.sh", "--python", sys.executable], cwd=root,
                                  capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=600)

        def doctor(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, "scripts/doctor.py", "--fast", *args], cwd=root,
                                  capture_output=True, text=True, env=env, timeout=300)

        r = setup()
        out = r.stdout + r.stderr
        cl = root / "scripts/config.local"
        expect("setup writes config.local with KB_PYTHON", cl.exists() and f'KB_PYTHON = "{sys.executable}"' in cl.read_text(), out)
        expect("config.local is readable by the owner only", cl.exists() and stat.S_IMODE(cl.stat().st_mode) == 0o600)
        hook = root / ".git/hooks/pre-commit"
        expect("the pre-commit check is installed", hook.exists() and "check_public.py --staged" in hook.read_text(), out)
        expect("the model is found in the cache", "already here" in out, out)
        expect("setup names the Keeper libraries to sync", "astro-kb-data" in out and "astro-kb-notes" in out, out)
        expect("the doctor at the end fails without the Keeper libraries",
               "FAIL" in out.split("== 7. Check")[-1] or "STOP" in out.split("== 7. Check")[-1], out)

        cl.write_text(cl.read_text() + SECRET + "\n")
        hook.write_text("#!/usr/bin/env bash\necho my own hook\n")
        r = setup()
        out = r.stdout + r.stderr
        expect("run again: the token line is kept, KB_PYTHON unchanged",
               SECRET in cl.read_text() and "KB_PYTHON unchanged" in out, out)
        expect("a pre-commit hook that is not ours is left alone",
               "my own hook" in hook.read_text() and "not ours" in out, out)
        expect("the token never appears in what setup or the doctor print", "not-a-real-token" not in out, out)

        d = lines_of(doctor().stdout)
        expect("the doctor: config.local OK, a foreign hook is a warning",
               d.get("scripts/config.local", "").startswith("OK") and d.get("pre-commit check", "").startswith("WARN"), d)
        expect("the doctor: keeper/ and live/ missing stop", d.get("keeper/", "").startswith("STOP")
               and d.get("live/", "").startswith("STOP"), d)

        os.chmod(cl, 0o644)
        d = lines_of(doctor().stdout)
        expect("the doctor warns when config.local is readable by others", "chmod 600" in d.get("scripts/config.local", ""), d)
        cl.write_text(f'KB_PYTHON = "/nowhere/python"\n{SECRET}\n')
        r = doctor()
        d = lines_of(r.stdout)
        expect("the doctor fails a KB_PYTHON that does not exist", "does not exist" in d.get("scripts/config.local", ""), d)
        expect("the doctor does not print the token", "not-a-real-token" not in r.stdout + r.stderr)
        git(root, "config", "--unset", "github.user")
        d = lines_of(doctor().stdout)
        expect("the doctor fails a missing github.user", d.get("git config github.user", "").startswith("FAIL"), d)
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
