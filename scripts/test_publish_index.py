#!/usr/bin/env python
"""Tests of scripts/publish_index.py on a small vault with a stand-in embedder (no model):
- only an index keeper publishes; a member is refused;
- publishing refuses local changes to tracked files and a branch other than main;
- the first publish starts from the local index and embeds nothing new;
- a second publish embeds only the new note, archives the first version, records the change
  in keeper/index/history.jsonl and copies the result to index/;
- the history is in Keeper, not in the repository;
- --pull copies a newer published index; --restore brings back an archived version.
Needs lancedb (the knowledge base's environment).

    python scripts/test_publish_index.py
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

CHILD = r'''
import hashlib, json, sys
sys.path.insert(0, "scripts")
import publish_index as pi
from kb_pkg import index, config
from kb_pkg.store import Store

class Fake:
    """8 numbers per text from its hash."""
    calls = 0
    def embed_passages(self, texts):
        Fake.calls += len(texts)
        return [[b / 255 for b in hashlib.sha256(t.encode()).digest()[:8]] for t in texts]

what = sys.argv[1]
if what == "local":
    print(json.dumps(index.build(Store(config.INDEX_DIR), Fake())))
elif what == "publish":
    m = pi.publish("cpu", 3, embedder=Fake(), check=False)
    print(json.dumps({"meta": m, "embedded": Fake.calls}))
elif what == "pull":
    pi.pull()
elif what == "restore":
    pi.restore(sys.argv[2])
'''


def expect(name: str, ok: bool, detail="") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        print("     " + str(detail).strip().replace("\n", "\n     ")[:3000])


def note(root: Path, rel: str, title: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntitle: {title}\ntype: note\ncreated: '2026-11-13'\nauthor: keeper1\ntags: [Gaia]\n---\n"
                 f"# {title}\n\n{body}\n", encoding="utf-8")


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", CHILD, *args], cwd=root, capture_output=True, text=True)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def last_json(r: subprocess.CompletedProcess) -> dict:
    return json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else {}


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / "vault"
        (root / "scripts").mkdir(parents=True)
        for s in ("kb_common.py", "publish_index.py", "check_vault.py"):
            shutil.copy(REPO / "scripts" / s, root / "scripts")
        shutil.copytree(REPO / "scripts/kb_pkg", root / "scripts/kb_pkg",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (root / "scripts/build").mkdir()
        shutil.copy(REPO / "scripts/build/paper_text.py", root / "scripts/build")
        shutil.copy(REPO / "conventions.yaml", root)
        shutil.copy(REPO / ".gitignore", root)
        (root / "sources.yaml").write_text("repositories: []\ngaia: []\n")
        owner = __import__("yaml").safe_load((REPO / "conventions.yaml").read_text())["owner"]
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "t@example.org")
        git(root, "config", "user.name", "t")
        git(root, "config", "github.user", "member1")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "skeleton")
        note(root, "live/gaia/notes/Parallax zero point.md", "Parallax zero point",
             "The parallax zero point depends on magnitude, colour and position. " * 5)
        (root / "keeper/locks").mkdir(parents=True)

        r = run(root, "local")
        expect("a local index is built", r.returncode == 0, r.stdout + r.stderr)

        r = run(root, "publish")
        expect("a member cannot publish", r.returncode != 0 and "not an index keeper" in r.stderr, r.stdout + r.stderr)
        git(root, "config", "github.user", owner)

        (root / "sources.yaml").write_text("repositories: []\ngaia: []\n# edited\n")
        r = run(root, "publish")
        expect("publishing refuses local changes to tracked files",
               r.returncode != 0 and "Commit or stash" in r.stderr, r.stdout + r.stderr)
        git(root, "checkout", "-q", "sources.yaml")
        git(root, "switch", "-q", "-c", "other")
        r = run(root, "publish")
        expect("publishing refuses a branch other than main",
               r.returncode != 0 and "main branch" in r.stderr, r.stdout + r.stderr)
        git(root, "switch", "-q", "main")

        r = run(root, "publish")
        d = last_json(r)
        m = d.get("meta", {})
        v1 = m.get("version", "")
        expect("the first publish starts from the local index: nothing new to embed",
               r.returncode == 0 and d.get("embedded") == 0 and m.get("notes") == 1, r.stdout + r.stderr)
        expect("the version records the arm counts, the note hash and the model revision",
               m.get("passages_by_arm", {}).get("gaia", 0) > 0 and len(m.get("notes_hash", "")) == 16
               and m.get("model_revision"), m)
        k = root / "keeper/index"
        expect("the index is published in keeper/index/current", (k / "current/index_meta.json").exists())
        expect("the history is in Keeper, not in the repository",
               (k / "history.jsonl").exists() and not (root / "index_history.jsonl").exists())

        note(root, "live/gaia/notes/RUWE.md", "RUWE", "RUWE above 1.4 points to a poor single-star fit. " * 5)
        r = run(root, "publish")
        d = last_json(r)
        m2 = d.get("meta", {})
        expect("the second publish embeds only the new note and records it as added",
               r.returncode == 0 and d.get("embedded", 0) > 0 and m2.get("changed") == {"added": 1, "updated": 0, "removed": 0}
               and m2.get("previous") == v1, r.stdout + r.stderr)
        expect("the first version is archived", (k / "archive" / v1).is_dir(), list((k / "archive").glob("*")))
        hist = [json.loads(l) for l in (k / "history.jsonl").read_text().splitlines()]
        expect("the history has one line per publish and names the added note",
               len(hist) == 2 and "live/gaia/notes/RUWE.md" in hist[1]["changes_sample"]["added"], hist)
        local = json.loads((root / "index/index_meta.json").read_text())
        expect("index/ holds the published version", local.get("version") == m2.get("version"), local)

        shutil.rmtree(root / "index")
        r = run(root, "pull")
        expect("--pull copies the published index",
               r.returncode == 0 and json.loads((root / "index/index_meta.json").read_text())["version"] == m2["version"],
               r.stdout + r.stderr)
        r = run(root, "pull")
        expect("--pull says when the local index is current", "is the published version" in r.stdout, r.stdout)

        r = run(root, "restore", v1)
        cur = json.loads((k / "current/index_meta.json").read_text())
        expect("--restore brings back the archived version and archives the replaced one",
               r.returncode == 0 and cur["version"] == v1 and (k / "archive" / m2["version"]).is_dir()
               and json.loads((root / "index/index_meta.json").read_text())["version"] == v1, r.stdout + r.stderr)
        expect("no lock is left behind", not (k / "LOCK").exists())
        st = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True).stdout
        expect("git sees nothing new (index, keeper and live are ignored)", st.strip() == "", st)
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
