#!/usr/bin/env python
"""Build the Gaia papers of a release from ESA's papers page (index keeper / curator only).

For one `gaia:` entry of sources.yaml with `papers: page:`:
  1. freeze   ESA's papers page into keeper/data/gaia/<label>/papers-page-<date>.html, with a
              lock (--refresh takes a new copy; otherwise the newest copy is used);
  2. list     every paper on it (heading, topic, title, first author, DOI, arXiv id, ADS
              link, withdrawn or not) -> keeper/parsed/gaia/<label>/papers.jsonl;
  3. ingest   each paper not yet in the knowledge base with scripts/ingest_paper.py
              (arm `gaia`; metadata from SciX if a token is set, else from Crossref and
              arXiv; PDF from arXiv) -> paper and BibTeX notes in outbox/papers/,
              PDFs and locks in keeper/; publish the notes with /publish.

    python scripts/build/gaia_papers.py DR3 --list           # steps 1-2 only, print the list
    python scripts/build/gaia_papers.py DR3 [--refresh] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kb_common import KEEPER, ROOT, find_paper, github_user, normalize_id, today  # noqa: E402

import gaia_datamodel as gdm  # noqa: E402  (lock)
import html_snapshot  # noqa: E402  (AGENT)

TOPIC_TAGS = {"non-single stars": ["NSS"], "catalogue validation": ["Validation"],
              "performance verification": ["Validation"]}


def entry(label: str) -> dict:
    for e in yaml.safe_load((ROOT / "sources.yaml").read_text()).get("gaia", []):
        if e.get("label") == label:
            if "papers" not in e:
                sys.exit(f"sources.yaml: '{label}' has no papers: entry")
            return e
    sys.exit(f"sources.yaml: no gaia entry with label '{label}'")


def frozen_page(e: dict, refresh: bool, user: str) -> Path:
    folder = KEEPER / "data" / "gaia" / e["label"]
    folder.mkdir(parents=True, exist_ok=True)
    have = sorted(folder.glob("papers-page-*.html"))
    if have and not refresh:
        gdm.lock(have[-1], user, e["papers"]["page"])
        return have[-1]
    dest = folder / f"papers-page-{today()}.html"
    if not dest.exists():
        req = urllib.request.Request(e["papers"]["page"], headers={"User-Agent": html_snapshot.AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
    gdm.lock(dest, user, e["papers"]["page"])
    return dest


def parse_page(html: bytes) -> list[dict]:
    """Every paper paragraph on an ESA Gaia papers page, in page order."""
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html, "html.parser")
    main = s.find(id="content") or s.body
    out, heading, topic = [], "", ""
    for el in main.find_all(["h2", "h3", "h4", "p"]):
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if el.name in ("h2", "h3"):
            heading, topic = text, ""
            continue
        if el.name == "h4":
            topic = text
            continue
        links = el.find_all("a", href=True)
        doi = next((re.sub(r"^https?://(dx\.)?doi\.org/", "", a["href"]) for a in links if "doi.org/" in a["href"]), None)
        arxiv = next((normalize_id(a["href"])[1] for a in links if "arxiv.org/abs/" in a["href"]), None)
        ads = next((a["href"] for a in links if "adsabs.harvard.edu" in a["href"]), None)
        withdrawn = "withdrawn" in text.lower()
        if not (doi or arxiv or ads or (withdrawn and heading)):
            continue
        title_a = links[0] if links and links[0].get_text(strip=True).lower() not in ("arxiv", "ads") else None
        title = title_a.get_text(" ", strip=True) if title_a else text.split(" / ")[0]
        after = text[len(title):].strip() if text.startswith(title) else text
        author = re.split(r"\s*\(|,? et al", after)[0].strip(" ,.") or None
        bibcode = None
        if ads:
            m = re.search(r"abs/([^/?#]+)", ads.replace("%26", "&"))
            bibcode = m.group(1) if m else None
        out.append({"heading": heading, "topic": topic, "title": title, "first_author": author,
                    "doi": doi, "arxiv": arxiv, "ads_bibcode": bibcode, "withdrawn": withdrawn})
    return out


def tags_for(p: dict) -> list[str]:
    tags = ["Gaia", "DataRelease"]
    for key, extra in TOPIC_TAGS.items():
        if key in (p["topic"] + " " + p["heading"]).lower():
            tags += [t for t in extra if t not in tags]
    return tags


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("label")
    ap.add_argument("--refresh", action="store_true", help="take a new copy of ESA's page")
    ap.add_argument("--list", action="store_true", help="only freeze and list the papers")
    ap.add_argument("--limit", type=int, help="ingest at most N papers (a trial run)")
    a = ap.parse_args()
    e, user = entry(a.label), github_user()
    page = frozen_page(e, a.refresh, user)
    papers = parse_page(page.read_bytes())
    for x in e["papers"].get("extra", []):
        papers.append({"heading": "Extra (sources.yaml)", "topic": x.get("why", ""), "title": x["title"],
                       "first_author": None, "doi": x.get("doi"), "arxiv": x.get("arxiv"),
                       "ads_bibcode": None, "withdrawn": False})
    pdir = KEEPER / "parsed" / "gaia" / e["label"]
    pdir.mkdir(parents=True, exist_ok=True)
    with open(pdir / "papers.jsonl", "w") as fh:
        for p in papers:
            fh.write(json.dumps({**p, "page": e["papers"]["page"], "page_copy": page.name}, ensure_ascii=False) + "\n")
    usable = [p for p in papers if not p["withdrawn"] and (p["doi"] or p["arxiv"])]
    print(f"{len(papers)} entries on {page.name}: {len(usable)} to ingest, "
          f"{sum(p['withdrawn'] for p in papers)} withdrawn, "
          f"{sum(1 for p in papers if not p['withdrawn'] and not (p['doi'] or p['arxiv']))} without DOI or arXiv id")
    if a.list:
        for p in papers:
            print(f"  [{p['heading'][:22]:22s}|{p['topic'][:20]:20s}] {p['first_author'] or '?':18s} "
                  f"doi={p['doi'] or '-':32s} arXiv={p['arxiv'] or '-':11s} {'WITHDRAWN ' if p['withdrawn'] else ''}"
                  f"{p['title'][:60]}")
        return 0
    done = 0
    for p in usable:
        if a.limit is not None and done >= a.limit:
            break
        ident = p["doi"] or p["arxiv"]
        kind, value = normalize_id(ident if p["doi"] is None else f"https://doi.org/{p['doi']}")
        if find_paper(kind, value) or (p["arxiv"] and find_paper("arxiv", p["arxiv"])):
            print(f"exists   {ident}")
            continue
        cmd = [sys.executable, str(ROOT / "scripts/ingest_paper.py"), ident, "--arm", "gaia",
               "--tags", ",".join(tags_for(p)),
               "--source-list", f"ESA {e['label']} papers page ({page.name}): {p['heading']}"
                                + (f" / {p['topic']}" if p["topic"] else "")]
        if p["arxiv"]:
            cmd += ["--arxiv", p["arxiv"]]
        r = subprocess.run(cmd, capture_output=True, text=True)
        print((r.stdout.strip().splitlines() or [""])[0] or r.stderr.strip()[-300:])
        done += 1
    print("\nNext: check the notes in outbox/papers/, then /publish them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
