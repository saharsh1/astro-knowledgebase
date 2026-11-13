"""Text extraction from PDFs and notes, plus metadata helpers."""
import re
from pathlib import Path

import fitz  # pymupdf


def extract_pdf(path: Path) -> list[tuple[int, str]]:
    """Return [(page_number_1_indexed, text), ...] for a PDF."""
    pages: list[tuple[int, str]] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            pages.append((i, page.get_text("text")))
    return pages


def read_note(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def first_author(stem: str) -> str | None:
    """First-author surname from a filename stem like 'Doe et al (2025) - Title'."""
    head = stem.split("(", 1)[0].strip()
    if not head:
        return None
    # 'Doe et al', 'Smith and Jones', 'Doe & Roe', or 'Doe'
    token = re.split(r"\s+(?:et al|and|&)\b", head)[0].strip()
    return token.split()[0] if token else None


def paper_title(stem: str) -> str:
    """The descriptive title after ' - ', else the whole stem."""
    return stem.split(" - ", 1)[1].strip() if " - " in stem else stem.strip()
