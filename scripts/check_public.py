#!/usr/bin/env python
"""Guard for the public skeleton: refuse anything that must not be in a public repository.

This repository is public; the notes, data and member list live in Keeper (closed). A
file committed by mistake is public at once, and git history keeps it after deletion.
So this check runs before every /share and on every pull request. It looks at every
file git tracks (or would track, with --staged) and refuses:

- files outside the skeleton (ALLOWED below): no live/, keeper/, outbox/, sandbox/, ...
- PDFs, data and archives (BLOCKED_SUFFIXES), and any file over MAX_BYTES;
- text that looks like a token, a key or a private e-mail address.

    python scripts/check_public.py            # files in the last commit (git ls-files)
    python scripts/check_public.py --staged   # also files staged for the next commit

Exit status 1 on any finding. Only the owner changes the lists below.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Top-level entries a public skeleton may hold (a file, or a folder and all inside it).
ALLOWED = {
    ".claude", ".github", ".gitignore", ".mcp.json", ".obsidian/app.json",
    "CLAUDE.md", "README.md", "LICENSE", "LICENSE-docs.md",
    "conventions.yaml", "sources.yaml", "environment.yml",
    "docs", "demos", "scripts", "templates",
}
# Never in git, even inside an allowed folder.
BLOCKED_PARTS = {"live", "keeper", "outbox", "sandbox", "index", "external", ".index-staging",
                 ".resolve-trash", "__pycache__"}
BLOCKED_NAMES = {"config.local", "settings.local.json", "bookmarks.json", "workspace.json", "roles.yaml"}
BLOCKED_SUFFIXES = {".pdf", ".fits", ".fit", ".fz", ".csv", ".tsv", ".parquet", ".feather", ".h5", ".hdf5",
                    ".npy", ".npz", ".pkl", ".pickle", ".vot", ".votable", ".ecsv", ".db", ".sqlite",
                    ".lance", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".tar", ".png", ".jpg", ".jpeg"}
MAX_BYTES = 1_000_000

SECRETS = [
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}"), "a GitHub token"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "an Anthropic API key"),
    (re.compile(r"\bhf_[A-Za-z0-9]{30,}"), "a Hugging Face token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "an AWS key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\b\s*[:=]\s*['\"][A-Za-z0-9_\-./+]{16,}['\"]"),
     "a key or token assigned in the text"),
]
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b")
EMAIL_OK = re.compile(r"(@(example\.(org|com|net)|users\.noreply\.github\.com|anthropic\.com)|^git@github\.com)$",
                      re.I)                                    # git@github.com: the SSH remote, not a person


def tracked(staged: bool) -> list[str]:
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, text=True,
                           check=True).stdout.split("\0")
    if staged:
        files += subprocess.run(["git", "-C", str(ROOT), "diff", "--cached", "--name-only", "-z",
                                 "--diff-filter=ACMR"], capture_output=True, text=True,
                                check=True).stdout.split("\0")
    return sorted({f for f in files if f})


def problems(rel: str) -> list[str]:
    out = []
    parts = rel.split("/")
    if not (parts[0] in ALLOWED or rel in ALLOWED):
        out.append("not part of the skeleton (allowed: " + ", ".join(sorted(ALLOWED)) + ")")
    if hit := BLOCKED_PARTS.intersection(parts[:-1]):
        out.append(f"inside {'/'.join(sorted(hit))}/, which is never in git")
    if parts[-1] in BLOCKED_NAMES:
        out.append("a private or per-machine file")
    if Path(rel).suffix.lower() in BLOCKED_SUFFIXES:
        out.append("a PDF, data, image or archive file: these go to Keeper")
    f = ROOT / rel
    if not f.is_file():
        return out
    size = f.stat().st_size
    if size > MAX_BYTES:
        out.append(f"{size / 1e6:.1f} MB, more than {MAX_BYTES / 1e6:.0f} MB")
        return out
    try:
        text = f.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return out + ["a binary file"]
    for pattern, what in SECRETS:
        if m := pattern.search(text):
            line = text.count("\n", 0, m.start()) + 1
            out.append(f"line {line}: looks like {what}")
    for m in EMAIL.finditer(text):
        if not EMAIL_OK.search(m.group(0)):
            line = text.count("\n", 0, m.start()) + 1
            out.append(f"line {line}: an e-mail address ({m.group(0)}); use name@example.org in examples")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true", help="also check files staged for the next commit")
    args = ap.parse_args()
    n = 0
    files = tracked(args.staged)
    for rel in files:
        if rel == "scripts/check_public.py":          # holds the patterns themselves
            continue
        for p in problems(rel):
            print(f"error: {rel}: {p}")
            n += 1
    print(f"{len(files)} files checked for the public repository: {n} error(s)")
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
