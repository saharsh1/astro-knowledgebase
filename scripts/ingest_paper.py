#!/usr/bin/env python
"""Ingest papers (curators only): PDF and lock into Keeper, paper and BibTeX notes into outbox/.

For each paper:
1. look it up in SciX (metadata, BibTeX, arXiv id, open-access sources);
2. stop if the knowledge base has it already (bibcode, arXiv id or DOI, in live/ or outbox/);
3. fetch the PDF from the publisher's open access or arXiv only (rule 1: public material),
   into keeper/pdfs/, and write its lock in keeper/locks/pdfs/;
4. write the paper note and the BibTeX note in outbox/papers/ (publish them with /publish).

Usage:
    python scripts/ingest_paper.py --list-requests
    python scripts/ingest_paper.py --request live/requests/<file>.md [...]
    python scripts/ingest_paper.py <bibcode|arXiv id|DOI|URL> ... --arm <arm> [--tags Gaia,NSS]
    python scripts/ingest_paper.py <id> --arm <arm> --pdf <local file>   # a PDF you have checked is public

Needs SCIX_TOKEN (environment, or the SCIX_TOKEN line of scripts/config.local).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from string import ascii_lowercase

from kb_common import (CONV, KEEPER, OUTBOX, ROOT, LIVE, find_paper, frontmatter, github_user, is_curator,
                       normalize_id, q, requests_, write_lock)

API = "https://api.scixplorer.org/v1"
GATEWAY = "https://scixplorer.org/link_gateway"
UA = {"User-Agent": "Mozilla/5.0 (knowledge-base paper ingest)"}
FL = "bibcode,title,author,year,abstract,doi,esources,identifier"
NOTE_ILLEGAL = ':/\\*?"<>|^#[]'
PDF_ILLEGAL = '/\\*?"<>|^#[]'
PDFS = KEEPER / "pdfs"


def token() -> str:
    t = os.environ.get("SCIX_TOKEN") or os.environ.get("ADS_DEV_KEY")
    cfg = ROOT / "scripts" / "config.local"
    if not t and cfg.exists():
        for line in cfg.read_text().splitlines():
            if line.strip().startswith("SCIX_TOKEN"):
                t = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not t:
        sys.exit("Set SCIX_TOKEN (environment or scripts/config.local) to a SciX/ADS API token.")
    return t.strip()


def sanitize(text: str, illegal: str) -> str:
    for ch in illegal:
        text = text.replace(ch, "_")
    return re.sub(r"\s+", " ", text).strip()


def plain_title(title: str) -> str:
    title = re.sub(r"<sup>(.*?)</sup>", r"^\1", title, flags=re.I)
    return re.sub(r"</?(?:sub|i|b|em)>", "", title, flags=re.I)


def scix_query(kind: str, value: str) -> str:
    return {"arxiv": f"arxiv:{value}", "doi": f"doi:{value}"}.get(kind, f'bibcode:"{value}"')


def fetch(kind: str, value: str, tok: str) -> dict:
    import requests
    h = {"Authorization": f"Bearer {tok}"}
    r = requests.get(f"{API}/search/query", params={"q": scix_query(kind, value), "fl": FL, "rows": 1},
                     headers=h, timeout=30)
    r.raise_for_status()
    docs = r.json()["response"]["docs"]
    if not docs:
        raise LookupError(f"SciX found nothing for {kind}:{value}")
    d = docs[0]
    b = requests.post(f"{API}/export/bibtex", json={"bibcode": [d["bibcode"]]}, headers=h, timeout=30)
    b.raise_for_status()
    bib = b.json()["export"].strip().replace("://ui.adsabs.harvard.edu/abs/", "://scixplorer.org/abs/")
    arxiv = next((i.split(":", 1)[1] for i in d.get("identifier", []) if i.lower().startswith("arxiv:")), None)
    return {"bibcode": d["bibcode"], "title": plain_title((d.get("title") or [""])[0]),
            "authors": d.get("author", []), "year": int(d["year"]),
            "abstract": (d.get("abstract") or "").strip(), "doi": (d.get("doi") or [None])[0],
            "esources": d.get("esources", []), "arxiv": arxiv, "bibtex": bib}


def prefix(authors: list[str]) -> str:
    names = [a.split(",", 1)[0].strip() for a in authors] or ["Anonymous"]
    return names[0] if len(names) == 1 else f"{names[0]} and {names[1]}" if len(names) == 2 else f"{names[0]} et al"


def bibtex_stem(pre: str, year: int, bibcode: str) -> str:
    """'<prefix> (<year>[letter]) - BibTeX', with a letter only when another paper took the name."""
    for letter in [""] + list(ascii_lowercase[1:]):
        stem = sanitize(f"{pre} ({year}{letter})", NOTE_ILLEGAL) + " - BibTeX"
        taken = [p for base in (LIVE / "papers" / "bibtex", OUTBOX / "papers" / "bibtex")
                 for p in [base / f"{stem}.md"] if p.exists()]
        if not taken or any(bibcode in p.read_text(encoding="utf-8") for p in taken):
            return stem
    raise RuntimeError("no free disambiguation letter")


def get_pdf(meta: dict, path: Path) -> str | None:
    """Publisher open access first, then arXiv. Nothing behind a paywall."""
    import requests
    urls = []
    if "PUB_PDF" in meta["esources"]:
        urls.append(("publisher open access", f"{GATEWAY}/{meta['bibcode']}/PUB_PDF"))
    if meta["arxiv"]:
        urls.append(("arXiv", f"https://arxiv.org/pdf/{meta['arxiv']}"))
    for source, url in urls:
        try:
            r = requests.get(url, headers=UA, timeout=120, allow_redirects=True)
        except requests.RequestException:
            continue
        if r.ok and ("application/pdf" in r.headers.get("Content-Type", "").lower() or r.content[:5] == b"%PDF-"):
            path.write_bytes(r.content)
            return source
        time.sleep(1)
    return None


def write_notes(m: dict, user: str, arm: str, tags: list[str], requested_by: str | None,
                pdf_name: str | None, pdf_source: str | None) -> Path:
    now = datetime.now().strftime("%Y-%m-%d")
    pre = prefix(m["authors"])
    stem = sanitize(f"{pre} ({m['year']}) - {m['title']}", NOTE_ILLEGAL)[:180]
    note = OUTBOX / "papers" / f"{stem}.md"
    bib = bibtex_stem(pre, m["year"], m["bibcode"])
    bib_note = OUTBOX / "papers" / "bibtex" / f"{bib}.md"
    bib_note.parent.mkdir(parents=True, exist_ok=True)
    fm = ["---", f"title: {q(stem)}", "type: paper", f"created: {now}", f"author: {user}",
          "tags: [" + ", ".join(tags) + "]", f"arms: [{arm}]",
          f"bibcode: {q(m['bibcode'])}", f"arxiv: {q(m['arxiv'] or '')}", f"doi: {q(m['doi'] or '')}",
          f"bibtex: {q(bib)}", f"pdf: {q('keeper/pdfs/' + pdf_name if pdf_name else '')}"]
    if requested_by:
        fm.append(f"requested_by: {requested_by}")
    fm += [f"paper_title: {q(m['title'])}", "paper_authors:"]
    fm += [f"  - {q(x)}" for x in m["authors"][:30]]
    if len(m["authors"]) > 30:
        fm.append("  - " + q(f"… and {len(m['authors']) - 30} more"))
    fm += [f"paper_year: {m['year']}", "---"]
    body = [f"[[{pdf_name}|The paper]] ({pdf_source})" if pdf_name else
            "> [!warning] No open-access PDF was found. A curator can add a public copy with --pdf.",
            "", f"https://scixplorer.org/abs/{m['bibcode']}/abstract", ""]
    if m["doi"]:
        body += [f"https://doi.org/{m['doi']}", ""]
    body += [f"[[{bib}]]", "", "# Abstract", "", m["abstract"], ""]
    note.write_text("\n".join(fm) + "\n" + "\n".join(body), encoding="utf-8")
    if not (LIVE / "papers" / "bibtex" / f"{bib}.md").exists() and not bib_note.exists():
        bib_note.write_text("\n".join(["---", f"title: {q(bib)}", "type: bibtex", f"created: {now}",
                                       f"author: {user}", "tags: []", "---"])
                            + "\n```bibtex\n" + m["bibtex"] + "\n```\n", encoding="utf-8")
    return note


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--arm", choices=list(CONV["arms"]))
    ap.add_argument("--tags", default="")
    ap.add_argument("--request", nargs="+", default=[], help="request notes to fulfil")
    ap.add_argument("--list-requests", action="store_true")
    ap.add_argument("--pdf", type=Path, help="a local PDF you have checked is public (one id only)")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args()

    if a.list_requests:
        rows = [r for r in requests_() if r["state"] == "open"]
        print("no open requests" if not rows else f"{len(rows)} open request(s):")
        for r in rows:
            print(f"  {r['path'].relative_to(ROOT)}\n     {r['kind']}:{r['id']}  arm={r['arm']}  "
                  f"by {r['by']} on {r['created']}: {r['reason']}")
        return 0

    user = github_user()
    if not is_curator(user):
        sys.exit(f"'{user}' is not a curator (conventions.yaml): ask for the paper with /request-paper.")
    jobs = []                                         # (kind, value, arm, requested_by)
    for rp in a.request:
        fm = frontmatter(ROOT / rp)
        if fm.get("type") != "request":
            sys.exit(f"{rp} is not a request note")
        kind, value = normalize_id(str(fm["id"]))
        jobs.append((kind, value, fm.get("arm"), fm.get("author")))
    for ident in a.ids:
        if not a.arm:
            ap.error("give --arm for papers that are not requests")
        jobs.append((*normalize_id(ident), a.arm, None))
    if not jobs:
        ap.error("nothing to ingest")
    if a.pdf and len(jobs) != 1:
        ap.error("--pdf works with one paper at a time")
    tags = [t.strip() for t in a.tags.split(",") if t.strip()]
    tok = token()
    PDFS.mkdir(parents=True, exist_ok=True)

    failed = 0
    for kind, value, arm, requested_by in jobs:
        if (have := find_paper(kind, value)):
            print(f"exists   {kind}:{value} -> {have.relative_to(ROOT)}")
            continue
        try:
            m = fetch(kind, value, tok)
        except Exception as e:                       # noqa: BLE001
            print(f"FAILED   {kind}:{value}: {e}")
            failed += 1
            continue
        if (have := find_paper("bibcode", m["bibcode"]) or (m["arxiv"] and find_paper("arxiv", m["arxiv"]))):
            print(f"exists   {m['bibcode']} -> {have.relative_to(ROOT)}")
            continue
        pdf_name = sanitize(f"{prefix(m['authors'])} ({m['year']}) - {m['title']}", PDF_ILLEGAL)[:180] + ".pdf"
        pdf_path, source = PDFS / pdf_name, None
        if pdf_path.exists():
            print(f"FAILED   {m['bibcode']}: keeper/pdfs/{pdf_name} exists but no paper note has this "
                  "paper; check by hand")
            failed += 1
            continue
        if a.pdf:
            shutil.copyfile(a.pdf, pdf_path)
            source = "local copy, checked public by the curator"
        elif not a.no_pdf:
            source = get_pdf(m, pdf_path)
        if source:
            write_lock(pdf_path, user, source)
        note = write_notes(m, user, arm, tags, requested_by, pdf_name if source else None, source)
        print(f"ok       {note.relative_to(ROOT)}  [pdf: {source or 'none'}]")
        time.sleep(0.5)
    print("\nNext: publish the notes in outbox/papers/ with /publish, then refresh the papers index.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
