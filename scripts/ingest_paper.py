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

Metadata: from SciX when SCIX_TOKEN is set (environment, or the SCIX_TOKEN line of
scripts/config.local); otherwise from public services that need no token: Crossref (title,
authors, year, BibTeX by DOI) and arXiv (abstract, and the PDF).
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
    return t.strip() if t else None


def sanitize(text: str, illegal: str) -> str:
    text = re.sub(r"\s*:\s+", ". ", text)                  # "Gaia DR3: Title" -> "Gaia DR3. Title"
    text = text.replace("/", "-")                            # "BP/RP" -> "BP-RP"
    for ch in illegal:
        text = text.replace(ch, "_")
    return re.sub(r"\s+", " ", text).strip()


def plain_title(title: str) -> str:
    """Title without HTML. Italic and bold tags become spaces: Crossref writes
    "<i>Gaia</i>Data Release 3", which would otherwise read "GaiaData"."""
    title = re.sub(r"<sup>(.*?)</sup>", r"^\1", title, flags=re.I)
    title = re.sub(r"<sub>", "", title, flags=re.I)
    title = re.sub(r"</sub>", " ", title, flags=re.I)
    title = re.sub(r"</?(?:i|b|em|scp)>", " ", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip()
    return re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"([(])\s+", r"\1", title))


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


ARXIV_API = "https://export.arxiv.org/api/query"
OPEN_UA = {"User-Agent": "astro-kb-builder/1 (paper metadata; one request at a time)"}


def arxiv_meta(arxiv: str) -> dict:
    """Title, authors, year, abstract and DOI of an arXiv paper (arXiv API, no token)."""
    import requests
    import xml.etree.ElementTree as ET
    r = requests.get(ARXIV_API, params={"id_list": arxiv}, headers=OPEN_UA, timeout=60)
    r.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    e = ET.fromstring(r.text).find("a:entry", ns)
    if e is None or e.find("a:title", ns) is None:
        raise LookupError(f"arXiv found nothing for {arxiv}")
    names = [a.findtext("a:name", "", ns).strip() for a in e.findall("a:author", ns)]
    authors = [f"{n.rsplit(' ', 1)[-1]}, {n.rsplit(' ', 1)[0]}" if " " in n else n for n in names]
    return {"title": re.sub(r"\s+", " ", e.findtext("a:title", "", ns)).strip(), "authors": authors,
            "year": int(e.findtext("a:published", "0000", ns)[:4]),
            "abstract": re.sub(r"\s+", " ", e.findtext("a:summary", "", ns)).strip(),
            "doi": (e.findtext("x:doi", "", ns) or "").strip() or None}


def fetch_open(kind: str, value: str, arxiv_hint: str | None = None) -> dict:
    """Metadata without a token: Crossref for a DOI (and its BibTeX), arXiv for the abstract."""
    import requests
    arxiv = value if kind == "arxiv" else arxiv_hint
    ax = arxiv_meta(arxiv) if arxiv else None
    doi = value if kind == "doi" else (ax or {}).get("doi")
    if kind == "bibcode" and not doi:
        raise LookupError("a bibcode needs SCIX_TOKEN; give the DOI or arXiv id instead")
    title, authors, year, bib = (ax or {}).get("title"), (ax or {}).get("authors", []), (ax or {}).get("year"), None
    if doi:
        r = requests.get(f"https://api.crossref.org/works/{doi}", headers=OPEN_UA, timeout=60)
        r.raise_for_status()
        w = r.json()["message"]
        main_t = " ".join((w.get("title") or [title or ""])[0].split())
        sub = " ".join((w.get("subtitle") or [""])[0].split())
        title = plain_title(f"{main_t}: {sub}" if sub and sub.lower() not in main_t.lower() else main_t)
        authors = [f"{a['family']}, {a.get('given', '')}".strip(", ") if a.get("family") else a.get("name", "")
                   for a in w.get("author", [])] or authors
        parts = (w.get("published-print") or w.get("published-online") or w.get("issued") or {}).get("date-parts")
        year = int(parts[0][0]) if parts and parts[0] and parts[0][0] else year
        b = requests.get(f"https://doi.org/{doi}", headers={**OPEN_UA, "Accept": "application/x-bibtex"}, timeout=60)
        if b.ok and b.text.lstrip().startswith("@"):
            import html as _html
            bib = _html.unescape(re.sub(r"</?(?:i|b|em|sub|sup|scp)>", "", b.text)).strip()
            bib = re.sub(r"[ \t]*\n[ \t]+(?=\S)", " ", bib)             # titles broken over lines
    if not title:
        raise LookupError(f"no metadata for {kind}:{value}")
    if not bib and arxiv:
        b = requests.get(f"https://arxiv.org/bibtex/{arxiv}", headers=OPEN_UA, timeout=60)
        bib = b.text.strip() if b.ok and b.text.lstrip().startswith("@") else None
    return {"bibcode": None, "title": title, "authors": authors, "year": year,
            "abstract": (ax or {}).get("abstract", ""), "doi": doi, "esources": [], "arxiv": arxiv,
            "bibtex": bib or f"% no BibTeX found for {kind}:{value}"}


def prefix(authors: list[str]) -> str:
    names = [a.split(",", 1)[0].strip() for a in authors] or ["Anonymous"]
    if "," not in (authors or [""])[0] and "collaboration" in names[0].lower() and len(names) > 1:
        return f"{names[0]}, {names[1]} et al"            # "Gaia Collaboration, Arenou et al"
    return names[0] if len(names) == 1 else f"{names[0]} and {names[1]}" if len(names) == 2 else f"{names[0]} et al"


def bibtex_stem(pre: str, year: int, key: str) -> str:
    """'<prefix> (<year>[letter]) - BibTeX', with a letter only when another paper took the name."""
    for letter in [""] + list(ascii_lowercase[1:]):
        stem = sanitize(f"{pre} ({year}{letter})", NOTE_ILLEGAL) + " - BibTeX"
        taken = [p for base in (LIVE / "papers" / "bibtex", OUTBOX / "papers" / "bibtex")
                 for p in [base / f"{stem}.md"] if p.exists()]
        if not taken or any(key in p.read_text(encoding="utf-8") for p in taken):
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
                pdf_name: str | None, pdf_source: str | None, source_list: str | None = None) -> Path:
    now = datetime.now().strftime("%Y-%m-%d")
    pre = prefix(m["authors"])
    stem = sanitize(f"{pre} ({m['year']}) - {m['title']}", NOTE_ILLEGAL)[:180]
    note = OUTBOX / "papers" / f"{stem}.md"
    bib = bibtex_stem(pre, m["year"], m["bibcode"] or m["doi"] or m["arxiv"] or m["title"])
    bib_note = OUTBOX / "papers" / "bibtex" / f"{bib}.md"
    bib_note.parent.mkdir(parents=True, exist_ok=True)
    fm = ["---", f"title: {q(stem)}", "type: paper", f"created: {now}", f"author: {user}",
          "tags: [" + ", ".join(tags) + "]", f"arms: [{arm}]",
          f"bibcode: {q(m['bibcode'] or '')}", f"arxiv: {q(m['arxiv'] or '')}", f"doi: {q(m['doi'] or '')}",
          f"bibtex: {q(bib)}", f"pdf: {q('keeper/pdfs/' + pdf_name if pdf_name else '')}"]
    if requested_by:
        fm.append(f"requested_by: {requested_by}")
    if source_list:
        fm.append(f"source_list: {q(source_list)}")
    fm.append(f"metadata_from: {'SciX' if m['bibcode'] else 'Crossref and arXiv'}")
    fm += [f"paper_title: {q(' '.join(m['title'].split()))}", "paper_authors:"]
    fm += [f"  - {q(x)}" for x in m["authors"][:30]]
    if len(m["authors"]) > 30:
        fm.append("  - " + q(f"… and {len(m['authors']) - 30} more"))
    fm += [f"paper_year: {m['year']}", "---"]
    body = [f"[[{pdf_name}|The paper]] ({pdf_source})" if pdf_name else
            "> [!warning] No open-access PDF was found. A curator can add a public copy with --pdf.",
            ""]
    if m["bibcode"]:
        body += [f"https://scixplorer.org/abs/{m['bibcode']}/abstract", ""]
    if m["arxiv"]:
        body += [f"https://arxiv.org/abs/{m['arxiv']}", ""]
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
    ap.add_argument("--arxiv", help="the paper's arXiv id, when the id given is a DOI (no-token metadata)")
    ap.add_argument("--source-list", help="where the paper was listed (e.g. ESA's DR3 papers page)")
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
        sys.exit(f"'{user}' is not a curator (keeper/roles.yaml): ask for the paper with /request-paper.")
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
            m = fetch(kind, value, tok) if tok else fetch_open(kind, value, a.arxiv)
        except Exception as e:                       # noqa: BLE001
            print(f"FAILED   {kind}:{value}: {e}")
            failed += 1
            continue
        if (have := (m["bibcode"] and find_paper("bibcode", m["bibcode"])) or (m["arxiv"] and find_paper("arxiv", m["arxiv"]))
                or (m["doi"] and find_paper("doi", m["doi"]))):
            print(f"exists   {m['bibcode'] or m['doi']} -> {have.relative_to(ROOT)}")
            continue
        pdf_name = sanitize(f"{prefix(m['authors'])} ({m['year']}) - {m['title']}", PDF_ILLEGAL)[:180] + ".pdf"
        pdf_path, source = PDFS / pdf_name, None
        if pdf_path.exists():
            print(f"FAILED   {m['bibcode'] or m['doi']}: keeper/pdfs/{pdf_name} exists but no paper note has this "
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
        note = write_notes(m, user, arm, tags, requested_by, pdf_name if source else None, source, a.source_list)
        print(f"ok       {note.relative_to(ROOT)}  [pdf: {source or 'none'}]")
        time.sleep(3)                                 # arXiv asks for a pause between requests
    print("\nNext: publish the notes in outbox/papers/ with /publish, then refresh the papers index.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
