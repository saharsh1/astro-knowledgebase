"""Shared data model for the knowledge-base index."""
from dataclasses import dataclass


@dataclass
class Chunk:
    chunk_id: str
    source_id: str
    source_type: str
    text: str
    title: str | None
    author: str | None
    page_start: int | None
    page_end: int | None
    section: str | None
    note_path: str | None
