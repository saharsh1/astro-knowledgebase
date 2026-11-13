"""On-disk LanceDB vector store plus a JSON file-hash manifest."""
import json
from pathlib import Path

import lancedb

from .model import Chunk

_TABLE = "chunks"


def _to_row(c: Chunk, vector: list[float]) -> dict:
    return {
        "vector": vector,
        "chunk_id": c.chunk_id,
        "source_id": c.source_id,
        "source_type": c.source_type,
        "text": c.text,
        "title": c.title or "",
        "author": c.author or "",
        "page_start": c.page_start if c.page_start is not None else -1,
        "page_end": c.page_end if c.page_end is not None else -1,
        "section": c.section or "",
        "note_path": c.note_path or "",
        "ordinal": int(c.chunk_id.rsplit("#", 1)[1]),
    }


def _from_row(row: dict) -> dict:
    def s(v):
        return v if v else None

    def n(v):
        return None if v is None or v == -1 else int(v)

    return {
        "text": row["text"],
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "ordinal": int(row["ordinal"]),     # passage number within the source; get_neighbors takes it
        "title": s(row["title"]),
        "author": s(row["author"]),
        "page_start": n(row["page_start"]),
        "page_end": n(row["page_end"]),
        "section": s(row["section"]),
        "note_path": s(row["note_path"]),
        "score": row.get("_distance"),
    }


class Store:
    def __init__(self, index_dir: Path):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(self.index_dir)

    def _table(self, sample_row: dict | None = None):
        if _TABLE in self.db.table_names():
            return self.db.open_table(_TABLE)
        if sample_row is None:
            return None
        return self.db.create_table(_TABLE, data=[sample_row])

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        rows = [_to_row(c, v) for c, v in zip(chunks, vectors)]
        source_ids = sorted({c.source_id for c in chunks})
        tbl = self._table()
        if tbl is not None:
            self.purge(source_ids)
            tbl = self._table()
        if tbl is None:
            tbl = self._table(sample_row=rows[0])
            rows = rows[1:]
        if rows:
            tbl.add(rows)

    def purge(self, source_ids: list[str]) -> None:
        tbl = self._table()
        if tbl is None or not source_ids:
            return
        quoted = ", ".join("'" + sid.replace("'", "''") + "'" for sid in source_ids)
        tbl.delete(f"source_id IN ({quoted})")

    def search(self, vector, k, *, source_type=None, author=None) -> list[dict]:
        tbl = self._table()
        if tbl is None:
            return []
        q = tbl.search(vector).limit(k)
        clauses = []
        if source_type:
            clauses.append("source_type = '" + source_type.replace("'", "''") + "'")
        if author:
            clauses.append("author = '" + author.replace("'", "''") + "'")
        if clauses:
            q = q.where(" AND ".join(clauses))
        return [_from_row(r) for r in q.to_list()]

    def neighbors(self, source_id: str, ordinal_range: range) -> list[dict]:
        tbl = self._table()
        if tbl is None:
            return []
        lo, hi = ordinal_range.start, ordinal_range.stop - 1
        sid = source_id.replace("'", "''")
        rows = (
            tbl.search()
            .where(f"source_id = '{sid}' AND ordinal >= {lo} AND ordinal <= {hi}")
            .limit(len(ordinal_range))
            .to_list()
        )
        rows.sort(key=lambda r: r["ordinal"])
        return [_from_row(r) for r in rows]

    def read_manifest(self) -> dict:
        f = self.index_dir / "manifest.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def write_manifest(self, m: dict) -> None:
        (self.index_dir / "manifest.json").write_text(json.dumps(m, indent=0))
