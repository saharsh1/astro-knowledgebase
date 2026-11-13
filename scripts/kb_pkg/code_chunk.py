"""Chunk source code for the index: one passage per function or class.

- Python: each top-level function and class is one passage; a class too long for
  the encoder is split into its methods (each passage keeps the class name). Code
  between definitions (imports, constants, scripts) becomes "module" passages.
- Notebooks: consecutive cells are merged up to the token limit; markdown cells
  are kept (they explain the code).
- Julia and other text: token windows.
Each passage starts with a header line `<repo>/<path>:<line> <kind> <name>` so the
embedding sees where it lives.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from .chunk import MAX_TOKENS, OVERLAP_TOKENS, _windows
from .model import Chunk


def _count(count, text: str) -> int:
    words = text.split()
    return sum(count(words)) if count else len(words)


def _split_long(text: str, count) -> list[str]:
    words = text.split()
    counts = count(words) if count else [1] * len(words)
    limit = MAX_TOKENS - 40
    if sum(counts) <= limit:
        return [text]
    return [" ".join(words[a:b]) for a, b in _windows(counts, limit, OVERLAP_TOKENS)]


def _python_units(src: str) -> list[tuple[str, str, int, int]]:
    """(kind, qualified name, first line, last line) units covering the module."""
    tree = ast.parse(src)
    lines = src.splitlines()
    units, covered = [], set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([d.lineno for d in node.decorator_list] + [node.lineno])
            end = node.end_lineno
            kind = "class" if isinstance(node, ast.ClassDef) else "def"
            units.append((kind, node.name, start, end, node))
            covered.update(range(start, end + 1))
    # module-level code between definitions
    run = []
    for i in range(1, len(lines) + 1):
        if i not in covered:
            if lines[i - 1].strip():
                run.append(i)
        elif run:                                   # a definition ends the module run
            units.append(("module", "", run[0], run[-1], None))
            run = []
    if run:
        units.append(("module", "", run[0], run[-1], None))
    units.sort(key=lambda u: u[2])
    return units


def chunk_code_file(repo: str, rel: str, path: Path, count=None) -> list[Chunk]:
    source_id = f"code:{repo}/{rel}"
    pieces: list[tuple[str, int, int, str]] = []          # (section, start, end, text)
    if path.suffix == ".py":
        src = path.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        try:
            units = _python_units(src)
        except SyntaxError:
            units = [("module", "", 1, len(lines), None)]
        for kind, name, a, b, node in units:
            body = "\n".join(lines[a - 1:b])
            if kind == "class" and node is not None and _count(count, body) > MAX_TOKENS:
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        sa = min([d.lineno for d in sub.decorator_list] + [sub.lineno])
                        pieces.append((f"{name}.{sub.name}", sa, sub.end_lineno,
                                       "\n".join(lines[sa - 1:sub.end_lineno])))
                head_end = min([s.lineno for s in node.body if isinstance(
                    s, (ast.FunctionDef, ast.AsyncFunctionDef))] + [b + 1]) - 1
                pieces.append((name, a, head_end, "\n".join(lines[a - 1:head_end])))
            else:
                pieces.append((name or "(module code)", a, b, body))
    elif path.suffix == ".ipynb":
        try:
            nb = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return []
        buf, first, last, cost = [], None, None, 0
        for i, c in enumerate(nb.get("cells", [])):
            text = "".join(c.get("source", []))
            if not text.strip():
                continue
            mark = "# [markdown]\n" if c.get("cell_type") == "markdown" else ""
            t = mark + text
            n = _count(count, t)
            if buf and cost + n > MAX_TOKENS - 40:
                pieces.append((f"cells {first}–{last}", first, last, "\n\n".join(buf)))
                buf, cost = [], 0
            if not buf:
                first = i
            buf.append(t)
            last = i
            cost += n
        if buf:
            pieces.append((f"cells {first}–{last}", first, last, "\n\n".join(buf)))
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        pieces.append(("", 1, text.count("\n") + 1, text))

    # fold very small pieces (< 60 tokens) into the next one, up to the token limit
    merged: list[tuple[str, int, int, str]] = []
    for sec, a, b, text in sorted(pieces, key=lambda x: x[1]):
        if merged and _count(count, merged[-1][3]) < 60 and \
                _count(count, merged[-1][3] + text) <= MAX_TOKENS - 40:
            ps, pa, pb, pt = merged[-1]
            merged[-1] = (f"{ps}; {sec}" if sec and ps != sec else ps, pa, b, pt + "\n" + text)
        else:
            merged.append((sec, a, b, text))
    pieces = merged

    chunks, ordinal = [], 0
    for section, a, b, text in pieces:
        if not text.strip():
            continue
        where = f"{repo}/{rel}:{a}" if path.suffix != ".ipynb" else f"{repo}/{rel} ({section})"
        for part in _split_long(text, count):
            chunks.append(Chunk(
                chunk_id=f"{source_id}#{ordinal}", source_id=source_id, source_type="code",
                text=f"{where} {section}\n{part}", title=repo, author=repo,
                page_start=a, page_end=b, section=section or None, note_path=f"{repo}/{rel}"))
            ordinal += 1
    return chunks
