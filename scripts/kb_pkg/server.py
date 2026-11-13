"""MCP server for the astro knowledge base (stdio).

Tools:
- search_kb        passages by meaning from notes, paper PDFs and the group's code
- get_neighbors    the passages around a hit
- lookup_column    exact record of one Gaia archive column (never a guess)
- find_columns     exact list of columns whose name or description contains a text
"""
import csv
import json
from functools import lru_cache

from mcp.server.fastmcp import FastMCP

from . import config
from . import search as search_mod

mcp = FastMCP("astro-kb")
_searcher = None


def _get_searcher():
    global _searcher
    if _searcher is None:
        _searcher = search_mod.build_default()
    return _searcher


def _page_label(hit):
    a, b = hit.get("page_start"), hit.get("page_end")
    if a is None:
        return None
    if hit["source_type"] == "code":
        unit = "cells" if (hit.get("note_path") or "").endswith(".ipynb") else "lines"
        if (hit.get("note_path") or "").endswith((".md", ".rst", ".txt")):
            return None
        return f"{unit} {a}–{b}" if b and b != a else f"{unit[:-1]} {a}"
    return f"p.{a}" if b is None or b == a else f"pp.{a}–{b}"


def _format_hit(hit: dict) -> dict:
    if hit["source_type"] == "paper":
        source = f"{hit.get('author') or '?'}: {hit.get('title') or hit['source_id']}"
    elif hit["source_type"] == "code":
        source = f"{hit.get('note_path')} ({hit.get('section') or 'module'})"
    else:
        source = hit.get("note_path") or hit["source_id"]
    return {"text": hit["text"], "source": source, "where": _page_label(hit),
            "section": hit.get("section"), "source_id": hit["source_id"], "ordinal": hit.get("ordinal"),
            "source_type": hit["source_type"], "score": hit.get("score")}


@mcp.tool()
def search_kb(query: str, k: int | None = None, source_type: str | None = None,
              author: str | None = None) -> list[dict]:
    """Search the astro knowledge base by meaning: notes (incl. the Gaia
    data-model notes and code cards), the curated papers' PDFs, and the group's
    code. Filter with source_type='note'|'paper'|'code'; author='<surname>' for
    papers or '<repository>' for code (e.g. 'orblet'). Cite as 'source, where'.
    For exact column names, types, units or flags use lookup_column instead."""
    hits = _get_searcher().search(query, k=k, source_type=source_type, author=author)
    return [_format_hit(h) for h in hits]


@mcp.tool()
def get_neighbors(source_id: str, ordinal: int = 0, radius: int = 1) -> list[dict]:
    """Passages next to a hit, for more context: pass the hit's source_id and ordinal."""
    return [_format_hit(h) for h in _get_searcher().get_neighbors(source_id, ordinal, radius=radius)]


@lru_cache(maxsize=1)
def _columns() -> dict:
    out = {}
    for label, path in config.PARSED_COLUMNS.items():
        if path.exists():
            for l in open(path):
                c = json.loads(l)
                out[(label, c["table"], c["column"])] = c
    if config.DR3_COLUMNS.exists():
        for r in csv.DictReader(open(config.DR3_COLUMNS)):
            t = r["table_name"].split(".", 1)[-1]
            out[("DR3 archive", t, r["column_name"])] = {
                "table": t, "column": r["column_name"], "datatype": r["datatype"],
                "unit": r["unit"] or None, "ucd": r["ucd"], "short_description": r["description"]}
    return out


@lru_cache(maxsize=1)
def _usage() -> dict:
    u = {}
    for name in ("papers", "code"):
        f = config.USAGE_DIR / f"{name}.jsonl"
        if f.exists():
            for l in open(f):
                r = json.loads(l)
                u[(name, r["table"], r["column"])] = r.get("papers") or r.get("uses")
    f = config.USAGE_DIR / "DR3-strict" / "usage.jsonl"
    if f.exists():
        for l in open(f):
            r = json.loads(l)
            u[("scix", r["table"], r["column"])] = r["n"]
    return u


@mcp.tool()
def lookup_column(table: str, column: str) -> dict:
    """Exact record of a Gaia archive column from the parsed data models (DR4
    draft data model, DR3 archive column list): type, unit, description, PDF pages,
    and where the curated papers and the group's code use it. Use this, never
    memory or search_kb, for column names, types, units and flag bits."""
    cols, use = _columns(), _usage()
    table = table.split(".")[-1]
    found = {label: rec for (label, t, c), rec in cols.items() if t == table and c == column}
    if not found:
        import difflib
        in_table = sorted({c for (_, t, c) in cols if t == table})
        close = difflib.get_close_matches(column, in_table, n=8, cutoff=0.6)
        other = sorted({f"{t}.{c}" for (_, t, c) in cols if c == column})[:12]
        similar = [f"{table}.{c}" for c in close] + other
        return {"found": False, "table": table, "column": column, "similar": similar}
    return {"found": True, "table": table, "column": column, "records": found,
            "note": f"[[DR4 draft - {table}#{column}]]" if "DR4 draft" in found else None,
            "curated_papers": use.get(("papers", table, column), []),
            "group_code": use.get(("code", table, column), []),
            "scix_papers_2022_2026": use.get(("scix", table, column))}


@mcp.tool()
def find_columns(text: str, table: str | None = None, limit: int = 50) -> list[dict]:
    """Exact list of columns whose name or short description contains `text`
    (case-insensitive), optionally within one table. Complete, not ranked."""
    t_low = text.lower()
    out = []
    for (label, t, c), rec in _columns().items():
        if table and t != table.split(".")[-1]:
            continue
        if t_low in c.lower() or t_low in (rec.get("short_description") or "").lower():
            out.append({"release": label, "table": t, "column": c, "datatype": rec.get("datatype"),
                        "unit": rec.get("unit"), "short_description": rec.get("short_description")})
    return sorted(out, key=lambda r: (r["release"], r["table"], r["column"]))[:limit]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
