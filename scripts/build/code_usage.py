#!/usr/bin/env python
"""Find where the group's code (external/, from sources.yaml) uses Gaia archive columns.

Searched: .py files, the code cells of .ipynb notebooks, .jl files.
A column counts as used when its name appears
- inside a string literal (e.g. t["ruwe"], "SELECT ruwe, parallax FROM ..."), or
- as an attribute (e.g. df.ruwe), or
- as `<table>.<column>`.
A use whose table is not named also needs the file to mention Gaia.
Plain variable names do not count (a local variable called `period` is not a
Gaia column). Names that are English words (e.g. `period`) need the table name
in the same file; names used by more than --max-shared tables (e.g. `source_id`)
count only as `<table>.<column>`. A use is credited to the tables named in the
repository; if none is named, to every table with that column (`table_named: false`).

The columns are those of every parsed data model in keeper/parsed/gaia/<release>/.
Writes keeper/parsed/usage/code.jsonl (read by lookup_column and software_docs.py).
Ported from the binary stars knowledge base.

Usage:
    python scripts/build/code_usage.py
"""
from __future__ import annotations

import argparse
import warnings
import ast
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
KEEPER = ROOT / "keeper"
warnings.filterwarnings("ignore", category=SyntaxWarning)
STRING = re.compile(r'("""|\'\'\'|"|\')((?:\\.|(?!\1).)*?)\1', re.S)
COMMON = {"corr", "flags", "hits", "notes", "prox", "logg", "mbol", "wavelength", "flux", "spectrum"}


def sources(path: Path) -> list[tuple[str, str, int]]:
    """(text, cell label, first line) blocks of code in a file."""
    if path.suffix == ".ipynb":
        try:
            nb = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            return []
        return [("".join(c.get("source", [])), f"cell {i}", 1)
                for i, c in enumerate(nb.get("cells", [])) if c.get("cell_type") == "code"]
    try:
        return [(path.read_text(encoding="utf-8"), "", 1)]
    except UnicodeDecodeError:
        return []


def code_spots(text: str, suffix: str):
    """String literals (not docstrings or bare strings) and attribute names, with their line.
    Python and notebooks are parsed; IPython magics and shell lines are dropped first."""
    if suffix == ".jl":
        text = re.sub(r"#.*", "", text)
        return [(text.count("\n", 0, m.start()) + 1, "string", m.group(2))
                for m in re.finditer(r'(""\"|")((?:\\.|(?!\1).)*?)\1', text, re.S)]
    clean = "\n".join("" if l.lstrip().startswith(("%", "!")) else l for l in text.splitlines())
    try:
        tree = ast.parse(clean)
    except SyntaxError:
        return None
    bare = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)}
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in bare:
            out.append((n.lineno, "string", n.value))
        elif isinstance(n, ast.Attribute):
            out.append((n.lineno, "attribute", n.attr))
    return out


def enclosing(text: str, line: int) -> str:
    """Name of the innermost function/class containing `line` (Python only)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ""
    best = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.lineno <= line <= getattr(node, "end_lineno", node.lineno):
                best = node.name
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(KEEPER / "parsed" / "usage" / "code.jsonl"))
    ap.add_argument("--max-shared", type=int, default=5)
    ap.add_argument("--max-per-file", type=int, default=3)
    a = ap.parse_args()

    tables_of = defaultdict(set)
    models = sorted((KEEPER / "parsed" / "gaia").glob("*/columns.jsonl"))
    if not models:
        raise SystemExit("no parsed data model in keeper/parsed/gaia/: build one first")
    for f in models:
        for l in open(f):
            c = json.loads(l)
            tables_of[c["column"]].add(c["table"])
    all_tables = {t for ts in tables_of.values() for t in ts}
    words = set()
    if Path("/usr/share/dict/words").exists():
        words = {w.strip().lower() for w in open("/usr/share/dict/words")}

    repos = yaml.safe_load((ROOT / "sources.yaml").read_text())["repositories"]
    hits = defaultdict(list)
    for repo in repos:
        base = ROOT / "external" / repo["name"]
        files = [f for f in base.rglob("*") if f.suffix in (".py", ".ipynb", ".jl")
                 and ".git" not in f.parts]
        blocks = [(f, *b) for f in files for b in sources(f)]
        found = defaultdict(list)
        for f, text, label, _ in blocks:
            spots = code_spots(text, f.suffix)          # (line, kind, string or attribute name)
            if spots is None:
                continue
            lines = text.splitlines()
            file_tables = {t for t in all_tables if re.search(rf"(?<![\w]){re.escape(t)}(?!\w)", text)}
            for col, tabs in tables_of.items():
                if col not in text:
                    continue
                lc = col.lower()
                plain = "_" not in col and (len(col) < 4 or lc in words or lc.rstrip("s") in words
                                            or lc in COMMON)
                shared = len(tabs) > a.max_shared
                pat = re.compile(rf"(?<![\w]){re.escape(col)}(?!\w)")
                qual = [re.compile(rf"(?<!\w){re.escape(t)}\.{re.escape(col)}(?!\w)") for t in tabs]
                for line, kind, s in spots:
                    tset, how = set(), kind
                    for t, q in zip(tabs, qual):
                        if q.search(s):
                            tset.add(t)
                            how = "table.column"
                    if not tset:
                        if shared:
                            continue
                        hit = (s == col) if kind == "attribute" else bool(pat.search(s))
                        if not hit:
                            continue
                        in_file = tabs & file_tables
                        if not in_file and "gaia" not in text.lower():
                            continue                     # file never mentions Gaia: not a Gaia column
                        if in_file:
                            tset, named_ok = in_file, True
                        elif plain:
                            continue                     # plain word, its table not named in the file
                        elif "_" in col:
                            tset, named_ok = set(tabs), False   # distinctive name, at most max_shared tables
                        elif "gaia_source" in tabs:
                            tset, named_ok = {"gaia_source"}, False
                        else:
                            continue                     # cannot tell which table
                    else:
                        named_ok = True
                    src = lines[line - 1].strip() if 0 < line <= len(lines) else ""
                    for t in tset:
                        found[(t, col)].append({
                            "repo": repo["name"], "commit": str(repo["commit"]),
                            "file": f.relative_to(base).as_posix(), "cell": label, "line": line,
                            "function": enclosing(text, line) if f.suffix == ".py" else "",
                            "code": src[:200], "how": how, "table_named": named_ok})
        for key, uses in found.items():
            per_file, seen = defaultdict(int), set()
            for u in sorted(uses, key=lambda u: (u["file"], u["line"])):
                k = (u["file"], u["cell"], u["line"])
                if k in seen or per_file[u["file"]] >= a.max_per_file:
                    continue
                seen.add(k)
                per_file[u["file"]] += 1
                hits[key].append(u)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w") as fh:
        for (t, col), uses in sorted(hits.items()):
            fh.write(json.dumps({"table": t, "column": col, "uses": uses}, ensure_ascii=False) + "\n")
    by_repo = defaultdict(set)
    for (t, col), uses in hits.items():
        for u in uses:
            by_repo[u["repo"]].add((t, col))
    print(f"{len(hits)} (table, column) pairs used in code;",
          ", ".join(f"{r}: {len(s)}" for r, s in sorted(by_repo.items())))


if __name__ == "__main__":
    main()
