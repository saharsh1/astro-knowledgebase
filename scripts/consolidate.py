#!/usr/bin/env python
"""Find what to consolidate, and gather the notes on one topic, for /consolidate.

Usage:
    python scripts/consolidate.py candidates [--min 2]
        Topics worth a topic note: an applies_to key (a Gaia column, a repository) that
        several notes share, and tags with several notes; each with the topic note that
        covers it already, if any.
    python scripts/consolidate.py gather [--applies-to KEY ...] [--tag TAG ...] [--title-has TEXT ...] [--arm ARM]
        The notes on one topic, oldest first: path, type, author, date, status, arm,
        which note supersedes it, and the topic notes that consolidate it already.

Nothing is written. The topic note itself is a draft in outbox/ (see /consolidate).
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from kb_common import CONV, LIVE, ROOT, frontmatter

LINK = re.compile(r"\[\[([^\]|#]+)")
SKIP_TYPES = {"bibtex", "request", "gaia-table", "gaia-section", "code-summary", "hub"}


def as_list(v) -> list:
    return [] if v in (None, "") else (v if isinstance(v, list) else [v])


def targets(v) -> list[str]:
    return [m.group(1).strip() for x in as_list(v) for m in [LINK.search(str(x))] if m]


def load() -> list[dict]:
    notes = []
    for arm in CONV["arms"]:
        for f in CONV["arm_folders"]:
            for p in sorted((LIVE / arm / f).rglob("*.md")) if (LIVE / arm / f).exists() else []:
                notes.append((p, arm))
    for f in CONV["shared_folders"]:
        for p in sorted((LIVE / f).rglob("*.md")) if (LIVE / f).exists() else []:
            notes.append((p, None))
    out = []
    for p, arm in notes:
        fm = frontmatter(p)
        if not fm or fm.get("type") in SKIP_TYPES or "SFConflict" in p.name:
            continue
        out.append({"path": p, "stem": p.stem, "arm": arm, "type": fm.get("type"), "author": fm.get("author"),
                    "created": str(fm.get("created", "")), "status": fm.get("status", ""),
                    "applies_to": [str(x) for x in as_list(fm.get("applies_to"))],
                    "tags": [str(x) for x in as_list(fm.get("tags"))],
                    "arms": [str(x) for x in as_list(fm.get("arms"))],
                    "supersedes": targets(fm.get("supersedes")),
                    "consolidates": targets(fm.get("consolidates")) if fm.get("type") == "topic" else []})
    return out


def relations(notes: list[dict]) -> tuple[dict, dict]:
    """(superseded_by, consolidated_in): note stem -> stems of the notes that replace / merge it."""
    sup, con = defaultdict(list), defaultdict(list)
    for n in notes:
        for t in n["supersedes"]:
            sup[t].append(n["stem"])
        for t in n["consolidates"]:
            con[t].append(n["stem"])
    return sup, con


def candidates(min_n: int) -> int:
    notes = load()
    sup, con = relations(notes)
    current = [n for n in notes if n["type"] != "topic" and n["stem"] not in sup]
    common = set(CONV["common_tags"])
    groups: dict[str, list[dict]] = defaultdict(list)
    for n in current:
        for key in n["applies_to"]:
            groups[f"applies_to {key}"].append(n)
        for tag in n["tags"]:
            if tag not in common:                      # 'Gaia' etc. would group almost everything
                groups[f"tag {tag}"].append(n)
    rows = []
    for key, ns in groups.items():
        ns = list({n["stem"]: n for n in ns}.values())
        if len(ns) < min_n:
            continue
        covered = sorted({t for n in ns for t in con.get(n["stem"], [])})
        uncovered = [n for n in ns if not con.get(n["stem"])]
        rows.append((len(uncovered), key, ns, covered))
    if not rows:
        print(f"no topic has {min_n} or more current notes")
        return 0
    rows.sort(key=lambda r: (-r[0], r[1]))
    print(f"{'new':>4} {'all':>4}  topic key")
    for n_new, key, ns, covered in rows:
        arms = sorted({n["arm"] or "shared" for n in ns})
        print(f"{n_new:4d} {len(ns):4d}  {key}   [{', '.join(arms)}]"
              + (f"   covered by: {'; '.join(covered)}" if covered else ""))
    print("\nnew = current notes not yet in any topic note; all = current notes with this key.")
    return 0


def gather(applies_to: list[str], tags: list[str], title_has: list[str], arm: str | None) -> int:
    if not (applies_to or tags or title_has):
        sys.exit("give --applies-to, --tag or --title-has")
    notes = load()
    sup, con = relations(notes)

    def match(n: dict) -> bool:
        if arm and n["arm"] != arm and arm not in n["arms"]:
            return False
        return (any(a in x for a in applies_to for x in n["applies_to"])
                or any(t in n["tags"] for t in tags)
                or any(s.lower() in n["stem"].lower() for s in title_has))

    hits = sorted((n for n in notes if match(n)), key=lambda n: (n["created"], n["stem"]))
    topics = sorted({t for n in hits for t in con.get(n["stem"], [])} |
                    {n["stem"] for n in hits if n["type"] == "topic"})
    if not hits:
        print("no notes match")
        return 0
    for n in hits:
        flags = []
        if n["stem"] in sup:
            flags.append("superseded by " + "; ".join(sup[n["stem"]]))
        if n["stem"] in con:
            flags.append("in topic " + "; ".join(con[n["stem"]]))
        print(f"{n['created'][:10]:10s} {str(n['type']):10s} {str(n['author']):12s} "
              f"{n['arm'] or 'shared':13s} {n['path'].relative_to(ROOT)}"
              + (f"\n{'':49s}status: {n['status']}" if n["status"] else "")
              + (f"\n{'':49s}" + " | ".join(flags) if flags else ""))
    print(f"\n{len(hits)} notes. Existing topic notes on this: {'; '.join(topics) if topics else 'none'}"
          + ("\nA new version of a topic note must say supersedes: [[<latest>]]." if topics else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates")
    c.add_argument("--min", type=int, default=2)
    g = sub.add_parser("gather")
    g.add_argument("--applies-to", nargs="+", default=[])
    g.add_argument("--tag", nargs="+", default=[])
    g.add_argument("--title-has", nargs="+", default=[])
    g.add_argument("--arm", choices=list(CONV["arms"]))
    a = ap.parse_args()
    if not LIVE.exists():
        sys.exit("live/ is missing: sync the Keeper library 'astro-kb-notes' into ./live first.")
    return candidates(a.min) if a.cmd == "candidates" else gather(a.applies_to, a.tag, a.title_has, a.arm)


if __name__ == "__main__":
    sys.exit(main())
