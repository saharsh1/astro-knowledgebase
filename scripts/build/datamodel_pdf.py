"""Parse a Gaia data-model PDF (e.g. the DR4 draft of 2026-06-26) into one record per
column. Used by gaia_datamodel.py; ported unchanged in its rules from the binary stars
knowledge base, where it parsed the same PDF with 141 of 141 tables and 4,629 columns.

The PDF layout this relies on (checked on the DR4 draft):
- the PDF outline lists groups (level 1) and tables (level 2) with start pages;
- a table title is a line in the large font (~14.3 pt) that names the table;
- a column entry starts with a line whose first span is in the large font at
  the left margin, of the form  `name : short description (type[, Quantity[unit]])`;
  the header can wrap onto the next line;
- running headers ("Draft", "CUx", "N/A") and footers ("Gaia DPAC Document",
  "Gaia DPAC CU9", page number) are dropped.

Embedded tables (e.g. flag bits) do not survive text extraction; columns whose
description overlaps a detected table are marked `has_embedded_table` with the
PDF pages, so a reader opens the page instead of trusting the text.

parse(pdf, ...) returns (tables, columns, report); write(out_dir, ...) writes
columns.jsonl, tables.jsonl and parse_report.json.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pymupdf

BIG = 13.5                      # font size threshold for titles and column names
LEFT = 80                       # x0 below this = left margin
RUNNING = {"Draft", "CUx", "N/A", "Gaia DPAC Document", "Gaia DPAC CU9"}
BULLET = re.compile(r"^[•–◦▪-]\s")


def last_paren(s: str) -> tuple[str, str] | None:
    """Split 'short (a, b)' at the last top-level parenthetical group."""
    s = s.rstrip()
    if not s.endswith(")"):
        return None
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            depth -= 1
            if depth == 0:
                return s[:i].strip(), s[i + 1:-1].strip()
    return None


TYPE_WORD = re.compile(r"^(long|integer|int|short|byte|unsignedByte|float|double|string|char|"
                       r"boolean|bool|text|timestamp|date)\b", re.I)


def typed(header: str) -> bool:
    """True if the header ends with a parenthetical group that starts with a data type."""
    p = last_paren(header.partition(":")[2].strip())
    return bool(p and TYPE_WORD.match(p[1]))


def split_type(paren: str) -> dict:
    dtype, _, rest = paren.partition(",")
    out = {"datatype": dtype.strip(), "quantity": None, "unit": None}
    rest = rest.strip()
    if rest:
        m = re.match(r"^(.*?)\s*\[(.*)\]$", rest)
        if m:
            out["quantity"], out["unit"] = m.group(1).strip() or None, m.group(2).strip()
        else:
            out["quantity"] = rest
    return out


def lines_of(doc: pymupdf.Document):
    """Yield (page_no, block_no, x0, y0, first_span_size, text) for content lines."""
    for pno, page in enumerate(doc, start=1):
        height = page.rect.height
        for bno, b in enumerate(page.get_text("dict")["blocks"]):
            for l in b.get("lines", []):
                text = "".join(s["text"] for s in l["spans"]).strip()
                if not text:
                    continue
                y0, y1 = l["bbox"][1], l["bbox"][3]
                if text in RUNNING and (y0 < 120 or y1 > height - 60):
                    continue
                if l["spans"][0]["size"] > 50:      # the large "Draft" watermark
                    continue
                if y1 > height - 60 and text.isdigit():
                    continue
                yield pno, bno, l["bbox"][0], y0, l["spans"][0]["size"], text


def dehyphenate_factory(doc: pymupdf.Document):
    words = Counter(re.findall(r"[A-Za-z]{3,}", "".join(p.get_text() for p in doc)))

    def join(prev: str, nxt: str) -> str:
        m1, m2 = re.search(r"([A-Za-z]+)-$", prev), re.match(r"([a-z]+)", nxt)
        if m1 and m2 and words.get(m1.group(1) + m2.group(1), 0) > 0:
            return prev[:-1] + nxt
        return prev + ("" if prev.endswith("-") else " ") + nxt
    return join


def embedded_tables(page) -> list:
    """Boxes of the tables on a page (flag bits, bit_index masks, ...).

    The data model draws its tables with horizontal rules only. PyMuPDF >= 2 finds such
    tables only with vertical_strategy="text"; that setting also returns the page frame
    (running-header rule to footer rule) and narrow formula blocks, which are dropped.
    Checked on the DR4 draft (2026-06-26) against the pages flagged with PyMuPDF 1.x:
    see scripts/test_build_datamodel.py."""
    boxes = [t.bbox for t in page.find_tables().tables]           # tables with full grids
    h = page.rect.height
    for t in page.find_tables(vertical_strategy="text", horizontal_strategy="lines").tables:
        x0, y0, x1, y1 = t.bbox
        frame = y0 <= 0.14 * h and y1 >= 0.93 * h                  # header rule to footer rule
        if not frame and x1 - x0 >= 200 and t.col_count >= 3:
            boxes.append(t.bbox)
    return boxes


def parse(pdf: Path, *, release: str, doc_version: str, label: str, status: str,
          find_tables: bool = True) -> tuple[list[dict], list[dict], dict]:
    """(tables, columns, report) of a data-model PDF. find_tables: detect embedded tables
    (flag bits etc.), about 0.35 s per page."""
    doc = pymupdf.open(pdf)
    toc = doc.get_toc()
    groups, table_group, table_page = [], {}, {}
    group = None
    for level, title, page in toc:
        title = title.strip()
        if level == 1:
            group = title
            groups.append(title)
        elif level == 2:
            table_group[title] = group
            table_page[title] = page
    join = dehyphenate_factory(doc)

    table_boxes: dict[int, list] = {}
    if find_tables:
        for pno, page in enumerate(doc, start=1):
            boxes = embedded_tables(page)
            if boxes:
                table_boxes[pno] = boxes

    tables, columns, unparsed_headers = [], [], []
    cur_table = cur_col = None
    in_columns = False
    prev_block = None
    pending_section = None

    def add_text(target: dict, key: str, text: str, new_par: bool):
        cur = target[key]
        if not cur:
            target[key] = text
        elif new_par or BULLET.match(text):
            target[key] = cur + "\n" + text
        else:
            last, _, head = cur.rpartition("\n")
            target[key] = (last + "\n" if _ else "") + join(head, text)

    def close_col():
        if cur_col:
            columns.append(cur_col)

    stream = list(lines_of(doc))
    spans: dict = {}                     # (page, column) -> [column, first y, last y] of its text
    i = 0
    while i < len(stream):
        pno, bno, x0, y0, size, text = stream[i]
        block_id = (pno, bno)
        new_par = block_id != prev_block
        prev_block = block_id

        if re.fullmatch(r"\d+(\.\d+)+", text):
            pending_section = text
            i += 1
            continue

        name_only = re.sub(r"\s*\[[A-Za-z ]+\]\s*$", "", text).strip()
        if size >= BIG and name_only in table_page and abs(pno - table_page[name_only]) <= 1 \
                and (cur_table is None or cur_table["table"] != name_only):
            close_col()
            cur_col = None
            cur_table = {"table": name_only, "group": table_group[name_only],
                         "section": pending_section, "page_start": pno,
                         "access": (re.search(r"\[([A-Za-z ]+)\]\s*$", text) or [None, None])[1],
                         "description": ""}
            tables.append(cur_table)
            in_columns = False
            pending_section = None
            i += 1
            continue
        pending_section = None

        if cur_table is None:
            i += 1
            continue

        if text.startswith("Columns description"):
            in_columns = True
            i += 1
            continue

        if in_columns and size >= BIG and x0 < LEFT and ":" in text:
            close_col()
            # A header may wrap onto at most 3 more lines; it ends with "(type...)".
            header, j = text, i
            while not typed(header) and j + 1 < len(stream) and j - i < 3:
                nxt = stream[j + 1]
                if nxt[4] >= BIG:
                    break
                j += 1
                header = join(header, nxt[5])
            if not typed(header):
                header, j = text, i          # leave the following lines to the description
            name, _, rest = header.partition(":")
            parsed = last_paren(rest.strip()) if typed(header) else None
            cur_col = {"release": release, "label": label, "status": status, "doc_version": doc_version,
                       "group": cur_table["group"], "table": cur_table["table"],
                       "column": name.strip(), "position": None,
                       "short_description": None, "datatype": None,
                       "quantity": None, "unit": None, "description": "",
                       "page_start": pno, "page_end": pno,
                       "has_embedded_table": False, "embedded_table_pages": []}
            if parsed:
                cur_col["short_description"] = parsed[0]
                cur_col.update(split_type(parsed[1]))
            else:
                cur_col["short_description"] = rest.strip()
                unparsed_headers.append(f"{cur_table['table']}.{name.strip()} (p. {pno}): {header}")
            cur_col["position"] = sum(c["table"] == cur_table["table"] for c in columns) + 1
            i = j + 1
            prev_block = None
            continue

        target, key = (cur_col, "description") if (in_columns and cur_col) else (cur_table, "description")
        add_text(target, key, text, new_par)
        if cur_col and in_columns:
            cur_col["page_end"] = pno
        spans.setdefault((pno, id(target)), [target, y0, y0])[2] = y0
        i += 1
    close_col()

    # A table belongs to the text that is running at its top edge: the last column (or table
    # description) on the page that starts above it, or, for a table at the top of a page,
    # the text continued from the previous page (the first on the page). Only the top edge
    # is used: a table drawn with rules only often extends to the footer rule in detection,
    # and rotated column headings are not in the text stream.
    for pno, boxes in table_boxes.items():
        on_page = sorted(((lo, id(x), x) for (pg, _), (x, lo, hi) in spans.items() if pg == pno),
                         key=lambda s: s[0])
        if not on_page:
            continue
        for bx in boxes:
            above = [x for lo, _, x in on_page if lo <= bx[1] + 25]
            owner = above[-1] if above else on_page[0][2]
            if "column" in owner:                             # a column, not a table description
                owner["has_embedded_table"] = True
                if pno not in owner["embedded_table_pages"]:
                    owner["embedded_table_pages"].append(pno)
                    owner["embedded_table_pages"].sort()

    for t in tables:
        t["n_columns"] = sum(c["table"] == t["table"] for c in columns)
    dup = [f"{t}.{c}" for (t, c), n in Counter((c["table"], c["column"]) for c in columns).items() if n > 1]
    report = {
        "pdf": Path(pdf).name, "pages": doc.page_count, "release": release, "label": label,
        "status": status, "doc_version": doc_version, "outline_groups": len(groups),
        "outline_tables": len(table_page), "tables_found": len(tables),
        "tables_missing": sorted(set(table_page) - {t["table"] for t in tables}),
        "tables_without_columns": [t["table"] for t in tables if t["n_columns"] == 0],
        "columns": len(columns), "unparsed_headers": unparsed_headers,
        "duplicate_columns": dup,
        "columns_without_unit": sum(c["unit"] is None for c in columns),
        "columns_with_embedded_table": sum(c["has_embedded_table"] for c in columns),
        "find_tables_run": find_tables,
    }
    return tables, columns, report


def write(out: Path, tables: list[dict], columns: list[dict], report: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "columns.jsonl", "w") as fh:
        for c in columns:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(out / "tables.jsonl", "w") as fh:
        for t in tables:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")
    (out / "parse_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
