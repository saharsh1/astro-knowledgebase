"""Runtime configuration for the knowledge base's search index.

Optional overrides in scripts/config.local (KEY = "value" lines, git-ignored).
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
INDEX_DIR = ROOT / "index"                 # git-ignored; each machine builds its own
EXTERNAL_DIR = ROOT / "external"           # code checkouts (scripts/fetch_code.py)
KEEPER_DIR = ROOT / "keeper"               # Keeper library "astro-kb-data" (read-only for members)
LIVE_DIR = ROOT / "live"                   # Keeper library "astro-kb-notes"
PARSED_COLUMNS = {                         # structured data models for the exact lookup
    "DR4 draft": KEEPER_DIR / "parsed" / "DR4-draft-2026-06-26" / "columns.jsonl",
}
DR3_COLUMNS = KEEPER_DIR / "data" / "gaia-docs" / "DR3" / "gaiadr3_tap_columns_2026-11-11.csv"
USAGE_DIR = KEEPER_DIR / "parsed" / "usage"

_DEFAULTS = {
    "KB_EMBEDDING_MODEL": "BAAI/bge-large-en-v1.5",
    "KB_MODEL_REVISION": "d4aa6901d3a41ba39fb536a557fa166f842b0e09",   # pinned: indexes from other revisions do not mix
    "KB_RERANKER_MODEL": "",       # empty => disabled
    "KB_DEFAULT_K": "12",
    "KB_DEVICE": "cpu",            # cpu | cuda | mps | auto
}


def conventions() -> dict:
    return yaml.safe_load((ROOT / "conventions.yaml").read_text())


def arms() -> list[str]:
    """The topical arms of conventions.yaml."""
    return list(conventions()["arms"])


def note_folders(arm: str | None = None) -> list[Path]:
    """Folders that hold notes. arm=None: every arm, the shared folders and the generated
    folders. arm=<name>: that arm's folders only. Folders not synced here are skipped."""
    conv = conventions()
    arms_ = [arm] if arm else list(conv["arms"])
    out = [LIVE_DIR / a / f for a in arms_ for f in conv["arm_folders"]]
    if arm is None:
        out += [LIVE_DIR / f for f in conv["shared_folders"]]
        out += [KEEPER_DIR / f for f in conv["generated_folders"]]
    return [f for f in out if f.is_dir()]


def arm_of(path: Path) -> str | None:
    """The arm a note belongs to (its folder), or None for shared and generated notes."""
    try:
        first = path.resolve().relative_to(LIVE_DIR.resolve()).parts[0]
    except (ValueError, IndexError):
        return None
    return first if first in conventions()["arms"] else None


def repositories() -> list[dict]:
    return yaml.safe_load((ROOT / "sources.yaml").read_text())["repositories"]


def _get(key: str) -> str | None:
    cfg = SCRIPTS_DIR / "config.local"
    if not cfg.exists():
        return None
    for line in cfg.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def embedding_model() -> str:
    return _get("KB_EMBEDDING_MODEL") or _DEFAULTS["KB_EMBEDDING_MODEL"]


def reranker_model() -> str | None:
    val = _get("KB_RERANKER_MODEL")
    if val is None:
        val = _DEFAULTS["KB_RERANKER_MODEL"]
    return val or None


def default_k() -> int:
    return int(_get("KB_DEFAULT_K") or _DEFAULTS["KB_DEFAULT_K"])


def device() -> str:
    return _get("KB_DEVICE") or _DEFAULTS["KB_DEVICE"]


def model_revision() -> str | None:
    return _get("KB_MODEL_REVISION") or _DEFAULTS["KB_MODEL_REVISION"] or None
