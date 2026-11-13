#!/usr/bin/env python
"""Request a paper: write a request note in outbox/requests/ for a curator to ingest.

Usage:
    python scripts/request_paper.py <arXiv id | DOI | bibcode | URL> --arm <arm> --reason "<why>"
    python scripts/request_paper.py --list            # every request and its state

A request holds identifiers only, never a PDF. It is not written when the paper is in the
knowledge base already, or when someone has an open request for it. Publish the request
with /publish (scripts/publish_notes.py --apply --only <file>).
"""
from __future__ import annotations

import argparse
import sys

from kb_common import CONV, OUTBOX, ROOT, find_paper, github_user, normalize_id, q, requests_, safe_id, today


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("id", nargs="?")
    ap.add_argument("--arm", choices=list(CONV["arms"]))
    ap.add_argument("--reason", default="")
    ap.add_argument("--list", action="store_true", help="list every request and its state")
    a = ap.parse_args()

    if a.list:
        rows = requests_()
        if not rows:
            print("no requests")
        for r in rows:
            print(f"{r['state']:8s} {r['kind']}:{r['id']:28s} {str(r['arm']):14s} {r['by']:12s} "
                  f"{r['created']:10s} {r['reason']}")
        return 0
    if not a.id or not a.arm:
        ap.error("give an identifier and --arm")
    if not a.reason.strip():
        ap.error("give --reason: one line on why the group needs the paper")

    try:
        kind, value = normalize_id(a.id)
    except ValueError as e:
        sys.exit(str(e))
    if (paper := find_paper(kind, value)):
        print(f"already in the knowledge base: {paper.relative_to(ROOT)}")
        return 0
    for r in requests_():
        if r["state"] == "open" and r["kind"] == kind and r["id"].lower() == value.lower():
            print(f"already requested by {r['by']} on {r['created']}: {r['path'].relative_to(ROOT)}")
            return 0

    user = github_user()
    stem = f"{today()} - {user} - {safe_id(value)}"
    path = OUTBOX / "requests" / f"{stem}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([
        "---", f"title: {q(stem)}", "type: request", f"id: {q(value)}", f"id_kind: {kind}",
        f"arm: {a.arm}", f"reason: {q(a.reason.strip())}", f"author: {user}",
        f"created: {today()}", "tags: []", "---", "",
        f"Request for {kind} `{value}` for the arm **{CONV['arms'][a.arm]['title']}**.", "",
    ]), encoding="utf-8")
    print(f"written {path.relative_to(ROOT)}")
    print(f"publish it: python scripts/publish_notes.py --apply --only {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
