#!/usr/bin/env python
"""Clone the code repositories of sources.yaml into external/ at their pinned commits.

Only the folders listed under `index:` are checked out (partial clone + sparse
checkout), so large data folders are never downloaded. external/ is git-ignored
and read-only (rule 8): change code in its own repository, never here. The search index
reads the code from here, labelled with the `software` arm.

Usage:
    python scripts/fetch_code.py            # all repositories
    python scripts/fetch_code.py orblet     # one
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "external"
DATA_EXT = ["fits", "fit", "fits.gz", "fz", "h5", "hdf5", "npy", "npz", "pkl", "pickle",
            "zip", "tar", "gz", "dat", "parquet", "feather"]


def git(*args: str, cwd: Path | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def main() -> None:
    repos = yaml.safe_load((ROOT / "sources.yaml").read_text())["repositories"]
    want = set(sys.argv[1:])
    EXT.mkdir(exist_ok=True)
    for r in repos:
        if want and r["name"] not in want:
            continue
        url = r["url"].split()[0]
        dest = EXT / r["name"]
        if not dest.exists():
            git("clone", "--quiet", "--filter=blob:none", "--no-checkout", url, str(dest))
        git("sparse-checkout", "init", "--no-cone", cwd=dest)
        patterns = ["/*", "!/*/"]                      # top-level files (README, pyproject, LICENSE, ...)
        for p in r.get("index", []):
            patterns += [f"/{p}", f"/{p}/**"]
        patterns += [f"!*.{ext}" for ext in DATA_EXT]          # never check out data files
        git("sparse-checkout", "set", "--no-cone", *patterns, cwd=dest)
        git("fetch", "--quiet", "origin", cwd=dest)
        git("-c", "advice.detachedHead=false", "checkout", "--quiet", str(r["commit"]), cwd=dest)
        head = git("rev-parse", "--short=12", "HEAD", cwd=dest)
        n = sum(1 for f in dest.rglob("*") if f.is_file() and ".git" not in f.parts)
        print(f"{r['name']:16s} {head}  {n} files")


if __name__ == "__main__":
    main()
