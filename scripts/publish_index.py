#!/usr/bin/env python
"""Publish, pull or restore the shared search index (kept in the Keeper library astro-kb-data).

Layout in keeper/index/:
    current/              the published index (LanceDB + manifest.json + index_meta.json + changes.json)
    archive/<version>/    earlier versions (the newest --keep are kept)
    history.jsonl         one line per publish or restore
    LOCK                  present while someone publishes
The history stays in Keeper, not in git: it names the notes that changed, and the notes are
private while this repository is public.

Each version records: who built it and when, the model and its pinned revision, a hash of the
indexing code, the skeleton commit, a hash of the note list (path + content of every note in
live/ and keeper/generated/), a hash of keeper/locks/ (the data files), the code pins, passages
per source type and per arm, the build time, and what was added, updated or removed.

Members do not need the published index: their own `python -m kb_pkg.index` adds what is new.
The published index saves them the first full build (about an hour on a laptop).

Usage (from the repository root, in the knowledge base's Python environment):
    python scripts/publish_index.py --status
    python scripts/publish_index.py --pull            members: copy a newer published index to index/
    python scripts/publish_index.py --publish         index keeper: update from the published index, publish
    python scripts/publish_index.py --restore <ver>   index keeper: roll back to an archived version
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kb_common import CONV, KEEPER, ROOT, github_user, roles  # noqa: E402

KEEPER_INDEX = KEEPER / "index"
CURRENT = KEEPER_INDEX / "current"
ARCHIVE = KEEPER_INDEX / "archive"
LOCK = KEEPER_INDEX / "LOCK"
HISTORY = KEEPER_INDEX / "history.jsonl"
LOCAL = ROOT / "index"
STAGING = ROOT / ".index-staging"
LOCK_STALE_H = 4


def sh(*args: str) -> tuple[int, str]:
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def meta_of(d: Path) -> dict:
    f = d / "index_meta.json"
    return json.loads(f.read_text()) if f.exists() else {}


def code_hash() -> str:
    """Hash of the indexing code: a change here can change the passages."""
    h = hashlib.sha256()
    for f in sorted((ROOT / "scripts" / "kb_pkg").glob("*.py")) + [ROOT / "scripts" / "build" / "paper_text.py"]:
        if f.exists():
            h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()[:12]


def tree_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(folder.rglob("*")) if folder.exists() else []:
        if f.is_file():
            h.update(f.relative_to(folder).as_posix().encode() + b"\0" + f.read_bytes())
    return h.hexdigest()[:16]


def notes_hash(manifest: dict) -> str:
    """Hash of the note list as indexed (path and content hash of every note)."""
    h = hashlib.sha256()
    for k in sorted(manifest):
        if k.endswith(".md"):
            h.update(f"{k} {manifest[k].split(' ')[0]}\n".encode())
    return h.hexdigest()[:16]


def is_index_keeper(user: str) -> bool:
    return user == CONV.get("owner") or user in (roles().get("index_keepers") or [])


def copy_index(src: Path, dst: Path) -> None:
    tmp = dst.with_name(dst.name + ".copying")
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp)
    if dst.exists():
        shutil.rmtree(dst)
    tmp.rename(dst)


def history() -> list[dict]:
    return [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()] if HISTORY.exists() else []


def next_version() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    n = 1
    for h in history():
        v = h.get("version", "")
        if v.startswith(today + "."):
            n = max(n, int(v.rsplit(".", 1)[1]) + 1)
    return f"{today}.{n}"


def require_clean_main() -> str:
    """The skeleton (code and rules) must be committed on main and, with a remote, equal to it."""
    _, branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        sys.exit(f"Publish from the main branch (this clone is on '{branch}').")
    _, dirty = sh("git", "status", "--porcelain", "--untracked-files=no")
    if dirty:
        sys.exit("Commit or stash the changes to tracked files first:\n" + dirty)
    _, remotes = sh("git", "remote")
    if "origin" in remotes.split():
        code, _ = sh("git", "fetch", "-q", "origin", "main")
        if code:
            sys.exit("Cannot reach origin to compare main: try again when online.")
        if sh("git", "rev-parse", "HEAD")[1] != sh("git", "rev-parse", "origin/main")[1]:
            sys.exit("Local main differs from origin/main: pull (or merge the pull request) first.")
        return "origin/main"
    print("Note: no remote 'origin'; the index records the local commit.")
    return "local main"


def take_lock(user: str) -> None:
    KEEPER_INDEX.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        info = json.loads(LOCK.read_text() or "{}")
        age_h = (time.time() - info.get("t", 0)) / 3600
        if age_h < LOCK_STALE_H:
            sys.exit(f"{info.get('who')} is publishing since {info.get('when')} (keeper/index/LOCK). "
                     f"Wait, or remove LOCK if it is older than {LOCK_STALE_H} h.")
    LOCK.write_text(json.dumps({"who": user, "machine": platform.node(), "t": time.time(),
                                "when": datetime.now().isoformat(timespec="minutes")}))


def append_history(entry: dict) -> None:
    KEEPER_INDEX.mkdir(parents=True, exist_ok=True)
    with open(HISTORY, "a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_checker() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_vault.py"), "--keeper"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.exit("The checker found errors; fix them before publishing:\n" + (r.stdout + r.stderr)[-3000:])


def publish(device: str, keep: int, embedder=None, check: bool = True) -> dict:
    from kb_pkg import config, index as kb_index
    from kb_pkg.embed import Embedder
    from kb_pkg.store import Store
    import yaml

    user = github_user()
    if not is_index_keeper(user):
        sys.exit(f"{user} is not an index keeper (the owner, or index_keepers: in keeper/roles.yaml). "
                 "Members use --pull, or build their own index.")
    base = require_clean_main()
    if check:
        run_checker()
    take_lock(user)
    try:
        prev = meta_of(CURRENT)
        model, revision = config.embedding_model(), config.model_revision()
        if prev and (prev.get("model"), prev.get("model_revision")) != (model, revision):
            sys.exit(f"The model changed ({prev.get('model')}@{str(prev.get('model_revision'))[:10]} -> "
                     f"{model}@{str(revision)[:10]}): passages from two models do not mix. "
                     "Build a new index by hand (python -m kb_pkg.index --rebuild), then publish.")
        if STAGING.exists():
            shutil.rmtree(STAGING)
        start = CURRENT if CURRENT.exists() else LOCAL if LOCAL.exists() else None
        if start:
            copy_index(start, STAGING)
        else:
            STAGING.mkdir(parents=True)
        store = Store(STAGING)
        old_manifest = store.read_manifest()
        t0 = time.time()
        stats = kb_index.build(store, embedder or Embedder(device=device), progress=embedder is None)
        new_manifest = store.read_manifest()
        changes = {
            "added": sorted(k for k in new_manifest if k not in old_manifest),
            "updated": sorted(k for k in new_manifest if k in old_manifest and new_manifest[k] != old_manifest[k]),
            "removed": sorted(k for k in old_manifest if k not in new_manifest),
        }
        rows = store.db.open_table("chunks").to_arrow().select(["source_type", "arms"]).to_pylist()
        by_type = dict(sorted(Counter(r["source_type"] for r in rows).items()))
        by_arm = dict(sorted(Counter(a for r in rows for a in r["arms"].strip("|").split("|") if a).items()))
        pins = {r["name"]: str(r["commit"]) for r in yaml.safe_load((ROOT / "sources.yaml").read_text())["repositories"]}
        version = next_version()
        meta = {
            "version": version, "action": "publish",
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "built_by": user, "machine": platform.node(), "device": device,
            "model": model, "model_revision": revision, "indexing_code": code_hash(),
            "skeleton_commit": sh("git", "rev-parse", "--short=12", "HEAD")[1], "skeleton_base": base,
            "notes": sum(1 for k in new_manifest if k.endswith(".md")), "notes_hash": notes_hash(new_manifest),
            "keeper_locks_hash": tree_hash(KEEPER / "locks"),
            "code_pins": pins, "sources": len(new_manifest),
            "passages": sum(by_type.values()), "passages_by_type": by_type, "passages_by_arm": by_arm,
            "build_seconds": round(time.time() - t0), "build": stats,
            "changed": {k: len(v) for k, v in changes.items()},
            "previous": prev.get("version"),
        }
        (STAGING / "index_meta.json").write_text(json.dumps(meta, indent=1))
        (STAGING / "changes.json").write_text(json.dumps(changes, indent=1, ensure_ascii=False))
        if CURRENT.exists():
            ARCHIVE.mkdir(parents=True, exist_ok=True)
            dest = ARCHIVE / (prev.get("version") or datetime.now().strftime("unversioned-%Y%m%d%H%M"))
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(CURRENT), str(dest))
            for old in sorted(ARCHIVE.iterdir())[:-keep] if keep > 0 else []:
                shutil.rmtree(old)
        shutil.move(str(STAGING), str(CURRENT))
        copy_index(CURRENT, LOCAL)
        append_history({**meta, "changes_sample": {k: v[:20] for k, v in changes.items()}})
        print(f"Published index {version}: {meta['passages']} passages from {meta['sources']} sources; "
              f"added {meta['changed']['added']}, updated {meta['changed']['updated']}, "
              f"removed {meta['changed']['removed']}; built in {meta['build_seconds']} s.")
        return meta
    finally:
        LOCK.unlink(missing_ok=True)
        if STAGING.exists():
            shutil.rmtree(STAGING, ignore_errors=True)


def restore(version: str) -> None:
    src = ARCHIVE / version
    if not src.exists():
        have = [p.name for p in sorted(ARCHIVE.iterdir())] if ARCHIVE.exists() else []
        sys.exit(f"No archived version {version}. Archived: {have or 'none'}")
    user = github_user()
    if not is_index_keeper(user):
        sys.exit(f"{user} is not an index keeper.")
    take_lock(user)
    try:
        prev = meta_of(CURRENT)
        if CURRENT.exists():
            shutil.move(str(CURRENT), str(ARCHIVE / (prev.get("version") or "replaced")))
        shutil.move(str(src), str(CURRENT))
        copy_index(CURRENT, LOCAL)
        append_history({"version": version, "action": "restore",
                        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "built_by": user, "machine": platform.node(), "replaced": prev.get("version")})
        print(f"Restored {version}; {prev.get('version')} moved to the archive.")
    finally:
        LOCK.unlink(missing_ok=True)


def pull() -> None:
    from kb_pkg import config
    pub, loc = meta_of(CURRENT), meta_of(LOCAL)
    if not pub:
        print("No published index in keeper/index/current (is the Keeper library synced?). "
              "Build your own: cd scripts && HF_HUB_OFFLINE=1 python -m kb_pkg.index")
        return
    if pub.get("model_revision") != config.model_revision():
        sys.exit(f"The published index uses model revision {str(pub.get('model_revision'))[:10]}, this clone "
                 f"{str(config.model_revision())[:10]}: /sync the skeleton first.")
    if loc.get("version") == pub["version"]:
        print(f"The local index is the published version {pub['version']}.")
        return
    if LOCK.exists():
        print("Someone is publishing right now (keeper/index/LOCK); try again later.")
        return
    copy_index(CURRENT, LOCAL)
    print(f"Copied the published index {pub['version']} (built by {pub.get('built_by')} on {pub.get('date')}). "
          "Add your own newer notes: cd scripts && HF_HUB_OFFLINE=1 python -m kb_pkg.index")


def status() -> None:
    pub, loc = meta_of(CURRENT), meta_of(LOCAL)
    print(f"published: {pub.get('version', 'none')}  by {pub.get('built_by', '-')}  {pub.get('date', '')}"
          + (f"  {pub.get('passages')} passages" if pub else ""))
    print(f"local:     {loc.get('version') or ('built on this machine' if (LOCAL / 'manifest.json').exists() else 'none')}")
    if ARCHIVE.exists():
        print("archive:  ", ", ".join(p.name for p in sorted(ARCHIVE.iterdir())) or "empty")
    for h in history()[-5:]:
        print(f"  {h['version']:14s} {h['action']:8s} {h.get('built_by', '')} {h.get('date', '')} "
              + (json.dumps(h.get("changed")) if h["action"] == "publish" else f"replaced {h.get('replaced')}"))
    if LOCK.exists():
        print("LOCK:     ", LOCK.read_text())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--publish", action="store_true")
    g.add_argument("--pull", action="store_true")
    g.add_argument("--restore", metavar="VERSION")
    g.add_argument("--status", action="store_true")
    ap.add_argument("--device", default="auto", help="auto | cpu | mps | cuda")
    ap.add_argument("--keep", type=int, default=3, help="archived versions to keep")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT / "scripts"))
    if a.publish:
        publish(a.device, a.keep)
    elif a.pull:
        pull()
    elif a.restore:
        restore(a.restore)
    else:
        status()


if __name__ == "__main__":
    main()
