#!/usr/bin/env python
"""Clean the text of the paper PDFs once, for search and for the column-usage scan.

For every PDF in keeper/pdfs/, writes keeper/parsed/papers/<pdf name>.json with the text of
each page after three repairs, and the counts of what was repaired:
  - ligatures (ﬁ ﬂ ﬀ ﬃ ﬄ ﬅ ﬆ) -> plain letters, so "ﬂag" is found by "flag";
  - a word split at a line end ("orbi-\\ntal") is joined only when the whole word occurs
    unbroken elsewhere in the same paper; otherwise the hyphen stays ("two-\\nbody" ->
    "two-body");
  - the reference list is marked, from its heading to the first appendix heading after it
    (A&A prints appendices after the references) or the end: `references` holds
    [start, end) character ranges per page, which the index leaves out
    (kb_pkg/extract.py: extract_paper).
A PDF whose SHA-256 matches the one recorded in its JSON is skipped.

    python scripts/build/paper_text.py [--force] [--only <pdf name>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_common import KEEPER  # noqa: E402

LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
             "ﬅ": "st", "ﬆ": "st"}
SPLIT = re.compile(r"([A-Za-z]{2,})-\n([a-z]{2,})")
REF_HEAD = re.compile(r"^[ \t]*(?:\d+\.?[ \t]*)?(References|REFERENCES|Bibliography|BIBLIOGRAPHY)[ \t]*$", re.M)
APPX_HEAD = re.compile(r"^[ \t]*(?:Appendix[ \t]+[A-Z]\b|APPENDIX\b|Online Material\b)", re.M)
ENTRY = re.compile(r"^[ \t]*(?:van |de |von |di |da |le |du )?[A-Z][A-Za-zÀ-ÿ'’\-]+(?: [A-Z][A-Za-zÀ-ÿ'’\-]+)?,"
                   r"[ \t]*(?:[A-Z][a-z]?\.|[A-Z]\.-[A-Z]\.)")                 # "Arenou, F." "Bailer-Jones, C. A. L."
CITED = re.compile(r"\b(19|20)\d\d[a-z]?\b.*\b(A&A|ApJ|ApJS|ApJL|AJ|MNRAS|PASP|PASJ|ARA&A|A&AS|AN|Nature|Science|Icarus|"
                   r"arXiv|Phys|J\.|Proc|SPIE|Messenger|IAU|in prep|submitted|accepted|Vol|ASP Conf)", re.I)
VERSION = "2"


def reference_lines(lines: list[str]) -> list[bool]:
    """Which lines of the stretch after the reference heading are reference entries: lines
    that start an entry ("Arenou, F., ...") or cite a year and a journal, plus up to two
    continuation lines between such lines. Figure captions, tables and acknowledgements
    printed after the list (arXiv versions, online tables) are not entries."""
    ref = [bool(ENTRY.match(l) or CITED.search(l)) for l in lines]
    out = ref[:]
    idx = [i for i, r in enumerate(ref) if r]
    for a, b in zip(idx, idx[1:]):
        if 1 < b - a <= 3:
            for k in range(a + 1, b):
                out[k] = True
    return out


def clean(pages: list[str]) -> tuple[list[str], list[list[list[int]]], dict]:
    """(cleaned pages, reference ranges per page, counts)."""
    n_lig = 0
    out = []
    for t in pages:
        for k, v in LIGATURES.items():
            n_lig += t.count(k)
            t = t.replace(k, v)
        out.append(t)
    words = Counter(w.lower() for w in re.findall(r"[A-Za-z]{3,}", "\n".join(out)))
    joined = kept = 0

    def fix(m: re.Match) -> str:
        nonlocal joined, kept
        whole = m.group(1) + m.group(2)
        if words.get(whole.lower(), 0) > 0:
            joined += 1
            return whole
        kept += 1
        return f"{m.group(1)}-{m.group(2)}"
    out = [SPLIT.sub(fix, t) for t in out]

    # The reference list: the last reference heading in the second half of the paper, up to
    # the first appendix heading after it.
    total = sum(len(t) for t in out)
    offsets, pos = [], 0
    for t in out:
        offsets.append(pos)
        pos += len(t) + 1
    full = "\n".join(out)
    heads = [m for m in REF_HEAD.finditer(full) if m.start() > total * 0.4]
    ranges: list[list[list[int]]] = [[] for _ in out]
    ref_chars = 0
    if heads:
        start = heads[-1].start()
        appx = APPX_HEAD.search(full, heads[-1].end())
        end = appx.start() if appx else len(full)
        segs, pos = [], start
        stretch = full[start:end].split("\n")
        for line, is_ref in zip(stretch, [True] + reference_lines(stretch[1:])):   # the heading itself too
            if is_ref and line.strip():
                if segs and segs[-1][1] >= pos - 1:
                    segs[-1][1] = pos + len(line)
                else:
                    segs.append([pos, pos + len(line)])
            pos += len(line) + 1
        ref_chars = sum(b - a for a, b in segs)
        for s0, s1 in segs:
            for i, t in enumerate(out):
                a, b = offsets[i], offsets[i] + len(t)
                lo, hi = max(a, s0), min(b, s1)
                if lo < hi:
                    if ranges[i] and ranges[i][-1][1] >= lo - a - 1:
                        ranges[i][-1][1] = hi - a
                    else:
                        ranges[i].append([lo - a, hi - a])
    return out, ranges, {"ligatures": n_lig, "words_joined": joined, "hyphens_kept": kept,
                         "references_found": bool(heads), "references_share": round(ref_chars / max(total, 1), 3)}


def process(pdf: Path, out_dir: Path, force: bool = False) -> dict | None:
    import pymupdf
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    out = out_dir / (pdf.name + ".json")
    if out.exists() and not force:
        old = json.loads(out.read_text())
        if old.get("sha256") == sha and old.get("version") == VERSION:
            return None
    with pymupdf.open(pdf) as doc:
        raw = [p.get_text("text") for p in doc]
    pages, ranges, stats = clean(raw)
    out_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"pdf": pdf.name, "sha256": sha, "version": VERSION, "stats": stats,
                               "pages": [{"page": i + 1, "text": t, "references": r}
                                         for i, (t, r) in enumerate(zip(pages, ranges))]},
                              ensure_ascii=False) + "\n")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only")
    a = ap.parse_args()
    pdfs = sorted((KEEPER / "pdfs").glob("*.pdf"))
    if a.only:
        pdfs = [p for p in pdfs if p.name == a.only]
    total = Counter()
    no_refs = []
    for pdf in pdfs:
        s = process(pdf, KEEPER / "parsed" / "papers", a.force)
        if s is None:
            continue
        total.update({k: v for k, v in s.items() if isinstance(v, int) and not isinstance(v, bool)})
        total["papers"] += 1
        if not s["references_found"]:
            no_refs.append(pdf.name)
        print(f"{s['ligatures']:5d} ligatures {s['words_joined']:5d} joined {s['hyphens_kept']:4d} kept "
              f"refs {s['references_share']:.2f}  {pdf.name[:80]}")
    print(f"\n{total['papers']} papers cleaned: {total['ligatures']} ligatures, {total['words_joined']} split "
          f"words joined, {total['hyphens_kept']} hyphens kept; no reference list found in {len(no_refs)}"
          + "".join(f"\n  {n}" for n in no_refs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
