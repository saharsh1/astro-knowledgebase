#!/usr/bin/env python
"""Tests of scripts/sync.py with a local stand-in for GitHub (a bare repository) and a
member's clone (no network, no model):
- an up-to-date clone is OK; a new commit on GitHub is pulled, and a change of the rules
  version is reported;
- changes to tracked files, another branch, or local commits on main stop the pull and
  leave the clone as it was;
- missing Keeper libraries stop; a missing locked file, a Seafile conflict copy and a
  draft in outbox/ are reported;
- a newer published index is copied from keeper/index/current; a note newer than the index
  is reported (--no-build).
Needs lancedb (the knowledge base's environment).

    python scripts/test_sync.py
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

BUILD = r'''
import hashlib, sys
sys.path.insert(0, "scripts")
from kb_pkg import index, config
from kb_pkg.store import Store
class Fake:
    def embed_passages(self, texts):
        return [[b / 255 for b in hashlib.sha256(t.encode()).digest()[:8]] for t in texts]
index.build(Store(config.INDEX_DIR), Fake())
print(config.model_revision())
'''


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


def ident(repo: Path) -> None:
    git(repo, "config", "user.email", "t@example.org")
    git(repo, "config", "user.name", "t")


def sync(root: Path, *args: str) -> tuple[int, dict[str, str], str]:
    r = subprocess.run([sys.executable, str(root / "scripts/sync.py"), "--no-build", *args],
                       cwd=root, capture_output=True, text=True)
    lines = {}
    for l in r.stdout.splitlines():
        if l[:4].strip() in ("OK", "DONE", "WARN", "STOP") and "  " in l:
            what = l[6:].split(":")[0]
            lines[what] = l
    return r.returncode, lines, r.stdout + r.stderr


def note(root: Path, rel: str, title: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntitle: {title}\ntype: note\ncreated: '2026-11-13'\nauthor: m1\ntags: [Gaia]\n---\n"
                 f"# {title}\n\n" + f"{title} is a note about Gaia. " * 10 + "\n", encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        owner, origin, member = tmp / "owner", tmp / "origin.git", tmp / "member"
        (owner / "scripts").mkdir(parents=True)
        for s in ("kb_common.py", "publish_index.py", "sync.py", "fetch_code.py", "snapshot_notes.py"):
            shutil.copy(REPO / "scripts" / s, owner / "scripts")
        shutil.copytree(REPO / "scripts/kb_pkg", owner / "scripts/kb_pkg", ignore=shutil.ignore_patterns("__pycache__"))
        (owner / "scripts/build").mkdir()
        shutil.copy(REPO / "scripts/build/paper_text.py", owner / "scripts/build")
        shutil.copy(REPO / "conventions.yaml", owner)
        shutil.copy(REPO / ".gitignore", owner)
        (owner / "sources.yaml").write_text("repositories: []\ngaia: []\n")
        git(tmp, "init", "-q", "-b", "main", str(owner))
        ident(owner)
        git(owner, "add", "-A")
        git(owner, "commit", "-qm", "skeleton")
        git(tmp, "clone", "-q", "--bare", str(owner), str(origin))
        git(owner, "remote", "add", "origin", str(origin))
        git(owner, "fetch", "-q", "origin")
        git(tmp, "clone", "-q", str(origin), str(member))
        ident(member)

        code, lines, out = sync(member)
        expect("without Keeper libraries the sync stops and says which library to sync",
               code == 1 and "astro-kb-data" in lines.get("keeper/", "") and "astro-kb-notes" in lines.get("live/", ""), out)
        (member / "keeper/locks/pdfs").mkdir(parents=True)
        (member / "keeper/pdfs").mkdir(parents=True)
        (member / "keeper/pdfs/a.pdf").write_bytes(b"%PDF-1.4 a")
        for name, size in (("a.pdf", 10), ("b.pdf", 5)):
            (member / f"keeper/locks/pdfs/{name}.json").write_text(json.dumps(
                {"path": f"pdfs/{name}", "size": size, "sha256": "0" * 64}))
        note(member, "live/gaia/notes/Zero point.md", "Zero point")
        code, lines, out = sync(member)
        expect("an up-to-date clone: the skeleton is OK", lines.get("skeleton", "").startswith("OK"), out)
        expect("a locked file not yet synced is reported", "1 of 2 locked files missing" in lines.get("keeper/", ""), out)
        expect("live/ with no conflicts is OK", lines.get("live/", "").startswith("OK"), out)
        expect("--full compares checksums too", "1 different" in sync(member, "--full")[1].get("keeper/", ""))

        (member / "live/gaia/notes/Zero point (SFConflict m2 2026-11-13).md").write_text("x")
        (member / "outbox").mkdir()
        (member / "outbox/Draft.md").write_text("x")
        code, lines, out = sync(member)
        expect("a Seafile conflict copy points to /resolve", "/resolve" in lines.get("live/", ""), out)
        expect("a draft in outbox/ points to /publish", "/publish" in lines.get("outbox/", ""), out)
        (member / "live/gaia/notes/Zero point (SFConflict m2 2026-11-13).md").unlink()

        conv = (owner / "conventions.yaml").read_text()
        old_v = next(l for l in conv.splitlines() if l.startswith("version:"))
        (owner / "conventions.yaml").write_text(conv.replace(old_v, "version: 99", 1))
        git(owner, "commit", "-qam", "rules 99")
        git(owner, "push", "-q", "origin", "main")

        (member / "sources.yaml").write_text("repositories: []\ngaia: []\n# mine\n")
        before = git(member, "rev-parse", "HEAD")
        code, lines, out = sync(member)
        expect("changes to tracked files stop the pull and keep the clone as it was",
               code == 1 and "/share" in lines.get("skeleton", "") and git(member, "rev-parse", "HEAD") == before
               and "# mine" in (member / "sources.yaml").read_text(), out)
        git(member, "checkout", "-q", "sources.yaml")
        git(member, "switch", "-q", "-c", "my-notes")
        code, lines, out = sync(member)
        expect("another branch stops the pull", code == 1 and "my-notes" in lines.get("skeleton", ""), out)
        git(member, "switch", "-q", "main")
        (member / "extra.txt").write_text("x")
        git(member, "add", "extra.txt")
        git(member, "commit", "-qm", "local")
        code, lines, out = sync(member)
        expect("local commits on main stop the pull", code == 1 and "1 commit(s) that GitHub does not" in lines.get("skeleton", ""), out)
        git(member, "reset", "-q", "--hard", before)

        code, lines, out = sync(member)
        expect("a new commit on GitHub is pulled and the new rules version is reported",
               lines.get("skeleton", "").startswith("DONE") and "to 99" in lines["skeleton"]
               and "version: 99" in (member / "conventions.yaml").read_text(), out)
        expect("--offline does not pull", "--offline" in sync(member, "--offline")[1].get("skeleton", ""))

        r = subprocess.run([sys.executable, "-c", BUILD], cwd=member, capture_output=True, text=True)
        expect("a stand-in index is built", r.returncode == 0, r.stdout + r.stderr)
        rev = r.stdout.strip().splitlines()[-1] if r.returncode == 0 else ""
        cur = member / "keeper/index/current"
        shutil.copytree(member / "index", cur)
        (cur / "index_meta.json").write_text(json.dumps({"version": "2026-11-14.1", "model_revision": rev,
                                                          "built_by": "owner", "date": "2026-11-14"}))
        shutil.rmtree(member / "index")
        code, lines, out = sync(member)
        expect("a newer published index is copied", "2026-11-14.1" in lines.get("published index", "")
               and lines["published index"].startswith("DONE"), out)
        expect("the copied index matches the files", lines.get("search index", "").startswith("OK"), out)
        note(member, "live/gaia/notes/RUWE.md", "RUWE")
        code, lines, out = sync(member)
        expect("a note newer than the index is reported (--no-build)", "1 new" in lines.get("search index", ""), out)
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
