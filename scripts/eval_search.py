#!/usr/bin/env python
"""Measure the search index with the questions of scripts/eval_questions.yaml.

For each question, the rank of the first passage from a right source in the top 20 (searched
with no filter, as search_kb does). Then: how many questions have a right source first, in
the top 3, 5 and 10; and how many different sources a top 10 holds on average. Run it before
and after any change to the passages, the model or the ranking, and compare.

    python scripts/eval_search.py [--per-source N] [--quiet]     (needs the index and the model)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    import yaml
    from kb_pkg import search
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--per-source", type=int, help="passages of one source in a list (default: the configured limit; 0: none)")
    ap.add_argument("--quiet", action="store_true", help="only the summary")
    a = ap.parse_args()
    qs = yaml.safe_load((Path(__file__).resolve().parent / "eval_questions.yaml").read_text())
    s = search.build_default()
    ranks, distinct = [], 0
    for q in qs:
        hits = s.search(q["question"], k=20, per_source=a.per_source)
        r = next((i + 1 for i, h in enumerate(hits) if any(x in h["source_id"] for x in q["right"])), None)
        ranks.append((q["kind"], r))
        distinct += len({h["source_id"] for h in hits[:10]})
        if not a.quiet:
            print(f"{str(r or '>20'):>4}  [{q['kind']:5s}] {q['question'][:72]:72s} | first: {hits[0]['source_id'][-48:] if hits else '-'}")

    def n(k: int, kind: str | None = None) -> str:
        sel = [r for kd, r in ranks if kind is None or kd == kind]
        return f"{sum(1 for r in sel if r and r <= k)}/{len(sel)}"
    print(f"\nright source first: {n(1)}   in the top 3: {n(3)}   top 5: {n(5)}   top 10: {n(10)}   top 20: {n(20)}")
    for kind in sorted({kd for kd, _ in ranks}):
        print(f"  {kind:5s} first {n(1, kind)}   top 5 {n(5, kind)}   top 10 {n(10, kind)}")
    print(f"different sources in a top 10, on average: {distinct / len(qs):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
