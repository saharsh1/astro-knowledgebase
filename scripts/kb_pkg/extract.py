"""Text extraction from PDFs and notes, plus metadata helpers."""
import hashlib
import json
import re
from pathlib import Path

import pymupdf


def extract_pdf(path: Path) -> list[tuple[int, str]]:
    """Return [(page_number_1_indexed, text), ...] for a PDF."""
    pages: list[tuple[int, str]] = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            pages.append((i, page.get_text("text")))
    return pages


def extract_paper(path: Path) -> tuple[list[tuple[int, str]], str]:
    """([(page, text)], how) of a paper PDF: the cleaned text without the reference list
    (keeper/parsed/papers/<name>.json, from scripts/build/paper_text.py) when it exists and
    was made from this very file; otherwise the raw text."""
    from . import config
    f = config.KEEPER_DIR / "parsed" / "papers" / (path.name + ".json")
    if f.exists():
        d = json.loads(f.read_text())
        if d.get("sha256") == hashlib.sha256(path.read_bytes()).hexdigest():
            pages = []
            for p in d["pages"]:
                t = p["text"]
                for a, b in sorted(p["references"], reverse=True):
                    t = t[:a] + t[b:]
                pages.append((p["page"], t))
            return pages, "cleaned"
    return extract_pdf(path), "raw"


def read_note(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def first_author(stem: str) -> str | None:
    """First-author surname from a filename stem like 'Doe et al (2025) - Title'."""
    head = stem.split("(", 1)[0].strip()
    if not head:
        return None
    m = re.match(r"^[\w\s-]*Collaboration,\s*(.+)$", head)     # "Gaia Collaboration, Klioner et al" -> "Klioner"
    if m:
        head = m.group(1).strip()
    # 'Doe et al', 'Smith and Jones', 'Doe & Roe', or 'Doe'
    token = re.split(r"\s+(?:et al|and|&)\b", head)[0].strip()
    return token.split()[0] if token else None


def paper_title(stem: str) -> str:
    """The descriptive title after ' - ', else the whole stem."""
    return stem.split(" - ", 1)[1].strip() if " - " in stem else stem.strip()
