"""Small helpers shared by the note scripts (publish, request, ingest). Standard library + PyYAML."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parent.parent


def conventions() -> dict:
    return yaml.safe_load((ROOT / "conventions.yaml").read_text())


CONV = conventions()
LIVE = ROOT / CONV["live_dir"]
KEEPER = ROOT / CONV["keeper_dir"]
OUTBOX = ROOT / CONV["outbox_dir"]


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    try:
        data = yaml.safe_load(text[4:end]) if end > 0 else None
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def github_user() -> str:
    user = subprocess.run(["git", "-C", str(ROOT), "config", "github.user"],
                          capture_output=True, text=True).stdout.strip()
    if not user:
        raise SystemExit("Set your GitHub user name first: git config github.user <name>")
    return user


def roles() -> dict:
    """keeper/roles.yaml ({curators: [...]}), kept in Keeper because this repository is public.
    Missing or unreadable: no curators besides the owner."""
    f = KEEPER / CONV.get("roles_file", "roles.yaml")
    try:
        r = yaml.safe_load(f.read_text()) if f.exists() else {}
    except yaml.YAMLError:
        r = {}
    return r if isinstance(r, dict) else {}


def is_curator(user: str) -> bool:
    return user == CONV.get("owner") or user in (roles().get("curators") or [])


def q(s: str) -> str:
    """A YAML double-quoted string."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ---- paper identifiers -------------------------------------------------------------------

def normalize_id(ident: str) -> tuple[str, str]:
    """(kind, value) for an arXiv id, DOI or bibcode, from a bare id or a URL.
    kind is 'arxiv', 'doi' or 'bibcode'. arXiv versions (v2) are dropped."""
    s = unquote(ident.strip())
    m = re.search(r"/abs/([^/?#]+)", s)
    if ("scixplorer.org" in s or "adsabs.harvard.edu" in s) and m:
        return "bibcode", m.group(1)
    m = re.search(r"(10\.\d{4,9}/\S+)", s)
    if m and (s.startswith("10.") or "doi" in s.lower()):
        return "doi", m.group(1).rstrip(".")
    m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", s)
    if m and (re.fullmatch(r"(arxiv:)?\d{4}\.\d{4,5}(v\d+)?", s, re.I) or "arxiv" in s.lower()):
        return "arxiv", m.group(1)
    if re.fullmatch(r"\d{4}[A-Za-z&.]{5}[\w.]{4}[A-Za-z.][\w.]{4}[A-Z.]", s):
        return "bibcode", s
    raise ValueError(f"not an arXiv id, DOI or bibcode: {ident!r}")


def safe_id(value: str) -> str:
    return re.sub(r"[/:\\*?\"<>|^#\[\]]", "_", value)


def paper_ids() -> dict[str, Path]:
    """'arxiv:<id>', 'doi:<doi>', 'bibcode:<code>' -> paper note, for every paper note in live/
    and in outbox/ (drafts count, so a paper is never ingested twice)."""
    out: dict[str, Path] = {}
    for base in (LIVE / "papers", OUTBOX / "papers"):
        for p in sorted(base.glob("*.md")) if base.exists() else []:
            fm = frontmatter(p)
            if fm.get("type") != "paper":
                continue
            for key in ("arxiv", "doi", "bibcode"):
                if fm.get(key):
                    out[f"{key}:{str(fm[key]).lower()}"] = p
    return out


def find_paper(kind: str, value: str) -> Path | None:
    return paper_ids().get(f"{kind}:{value.lower()}")


def requests_() -> list[dict]:
    """Every request note in live/requests/ and outbox/requests/, with its state:
    'done' (a paper note has its id), 'declined' (a discussion file is about it and says
    'Declined'), or 'open'."""
    ids = paper_ids()
    declined = set()
    for d in LIVE.glob("*/discussion/*.md") if LIVE.exists() else []:
        fm = frontmatter(d)
        if fm.get("type") == "discussion" and "declined" in d.read_text(encoding="utf-8").lower():
            m = re.match(r"\[\[([^\]|#]+)", str(fm.get("about", "")).strip())
            if m:
                declined.add(m.group(1).strip())
    out = []
    for base, where in ((LIVE / "requests", "live"), (OUTBOX / "requests", "outbox")):
        for p in sorted(base.glob("*.md")) if base.exists() else []:
            fm = frontmatter(p)
            if fm.get("type") != "request":
                continue
            try:
                kind, value = normalize_id(str(fm.get("id", "")))
            except ValueError:
                kind, value = "?", str(fm.get("id", ""))
            state = ("done" if f"{kind}:{value.lower()}" in ids else
                     "declined" if p.stem in declined else "open")
            out.append({"path": p, "where": where, "kind": kind, "id": value, "arm": fm.get("arm"),
                        "by": fm.get("author"), "reason": fm.get("reason", ""),
                        "created": str(fm.get("created", "")), "state": state})
    return out


# ---- Keeper locks ------------------------------------------------------------------------

def write_lock(file: Path, added_by: str, source: str) -> Path:
    """Write keeper/locks/<path>.json for a file in keeper/: size, SHA-256, who added it.
    One lock file per data file, so two curators never write the same file."""
    rel = file.resolve().relative_to(KEEPER.resolve()).as_posix()
    lock = KEEPER / "locks" / (rel + ".json")
    if lock.exists():
        raise FileExistsError(f"{lock} exists: a file with this name was added before")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({
        "path": rel, "size": file.stat().st_size,
        "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        "added_by": added_by, "added": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "source": source,
    }, indent=1) + "\n")
    return lock
