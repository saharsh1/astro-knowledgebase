"""Which notes use a Gaia column: the reverse view of the links from the arms into Gaia.

A note uses `<table>.<column>` when its `applies_to:` names it (e.g.
"dr3:nss_two_body_orbit.period") or its text links to the column's data-model note
("[[DR4 draft - nss_two_body_orbit#period]]"). Read from the synced notes at each call,
so it is never out of date. Standard library + PyYAML.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import config


def _frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    try:
        fm = yaml.safe_load(text[4:end]) if end > 0 else None
    except yaml.YAMLError:
        return {}
    return fm if isinstance(fm, dict) else {}


def notes_using_column(table: str, column: str) -> list[dict]:
    """[{note, arm, type, how}] for every note in live/ that uses table.column."""
    key = f"{table}.{column}".lower()
    link = re.compile(r"\[\[[^\]|#]*-\s*" + re.escape(table) + r"#" + re.escape(column) + r"[\]|]", re.I)
    out = []
    for folder in config.note_folders():
        if not folder.resolve().is_relative_to(config.LIVE_DIR.resolve()):
            continue                                   # generated notes are the data model itself
        for p in sorted(folder.rglob("*.md")):
            text = p.read_text(encoding="utf-8", errors="replace")
            fm = _frontmatter(text)
            pins = fm.get("applies_to") or []
            pins = pins if isinstance(pins, list) else [pins]
            how = []
            if any(str(x).lower().split(":", 1)[-1] == key for x in pins):
                how.append("applies_to")
            if link.search(text):
                how.append("link")
            if how:
                out.append({"note": f"[[{p.stem}]]", "arm": config.arm_of(p), "type": fm.get("type"),
                            "how": how})
    return out
