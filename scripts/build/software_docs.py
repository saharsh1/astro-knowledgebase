#!/usr/bin/env python
"""One generated summary note per pinned code repository (index keeper only).

For each repository in sources.yaml, checked out at its pin in external/ (scripts/fetch_code.py),
writes keeper/generated/software/Software - <repo>.md with:
  - the pin (full commit and its date), the URL, the licence, the folders that are indexed;
  - the start of the README;
  - the Python modules with the first line of their docstring and their public names;
  - the notebooks with their first heading;
  - the Gaia columns the code reads (keeper/parsed/usage/code.jsonl, scripts/build/code_usage.py),
    with links to the data-model notes and to the lines on GitHub at the pinned commit.
A member's code card (live/software/notes/<repo>.md) is linked when it exists. The code
itself is searched from external/, labelled with the `software` arm.

    python scripts/build/code_usage.py && python scripts/build/software_docs.py
"""
from __future__ import annotations

import ast
import json
import warnings
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_common import KEEPER, LIVE, ROOT, q, today  # noqa: E402

SCRIPT = "scripts/build/software_docs.py"
warnings.filterwarnings("ignore", category=SyntaxWarning)    # odd escapes in the code we only read
EXT = ROOT / "external"
RELEASE_ORDER = ["DR3", "EDR3", "DR4"]          # which data-model note a column links to first


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout.strip()


def readme_start(base: Path, limit: int = 1500) -> str:
    f = next((p for p in sorted(base.iterdir()) if p.name.lower().startswith("readme")), None) if base.exists() else None
    if not f:
        return ""
    text = f.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<!--.*?-->|<img[^>]*>|!\[[^\]]*\]\([^)]*\)", "", text, flags=re.S)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip() and not p.strip().startswith("[![")]
    out, n = [], 0
    for p in paras:
        if n + len(p) > limit and out:
            break
        out.append(re.sub(r"^#+\s*", "**", p, count=1) + ("**" if p.startswith("#") else ""))
        n += len(p)
    text = "\n\n".join(out)
    return text + ("\n```" if text.count("```") % 2 else "")        # never leave a code block open


def licence(base: Path) -> str:
    f = next((p for p in sorted(base.iterdir()) if p.name.upper().startswith(("LICENSE", "LICENCE", "COPYING"))), None) \
        if base.exists() else None
    if not f:
        return "no licence file"
    first = next((l.strip() for l in f.read_text(errors="replace").splitlines() if l.strip()), "")
    return f"{first} ({f.name})"


def modules(base: Path, folders: list[str]) -> list[dict]:
    out = []
    for f in sorted(base.rglob("*.py")):
        rel = f.relative_to(base).as_posix()
        if ".git" in f.parts or (folders and not any(rel == x or rel.startswith(x.rstrip("/") + "/") for x in folders)):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        doc = (ast.get_docstring(tree) or "").strip().split("\n")[0]
        public = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and not n.name.startswith("_")]
        out.append({"file": rel, "doc": doc, "public": public})
    return out


def notebooks(base: Path) -> list[dict]:
    out = []
    for f in sorted(base.rglob("*.ipynb")):
        if ".git" in f.parts or ".ipynb_checkpoints" in f.parts:
            continue
        try:
            nb = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        head = next((l.lstrip("# ").strip() for c in nb.get("cells", []) if c.get("cell_type") == "markdown"
                     for l in "".join(c.get("source", [])).splitlines() if l.startswith("#")), "")
        out.append({"file": f.relative_to(base).as_posix(), "title": head})
    return out


def data_model_tables() -> dict[str, set[str]]:
    """release label -> tables that have a generated data-model note."""
    out = {}
    for f in (KEEPER / "parsed" / "gaia").glob("*/tables.jsonl"):
        out[f.parent.name] = {json.loads(l)["table"] for l in open(f)}
    return out


def column_link(table: str, column: str, tables: dict[str, set[str]]) -> str:
    order = RELEASE_ORDER + sorted(set(tables) - set(RELEASE_ORDER))
    for label in order:
        if table in tables.get(label, set()):
            return f"[[{label} - {table}#{column}|{table}.{column}]]"
    return f"`{table}.{column}`"


def cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    repos = yaml.safe_load((ROOT / "sources.yaml").read_text())["repositories"]
    usage = [json.loads(l) for l in open(KEEPER / "parsed" / "usage" / "code.jsonl")] \
        if (KEEPER / "parsed" / "usage" / "code.jsonl").exists() else []
    tables = data_model_tables()
    out_dir = KEEPER / "generated" / "software"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("Software - *.md"):
        old.unlink()
    for r in repos:
        name, base = r["name"], EXT / r["name"]
        if not base.exists():
            print(f"skip {name}: no checkout in external/ (run scripts/fetch_code.py)")
            continue
        sha, date = git(base, "rev-parse", "HEAD"), git(base, "log", "-1", "--format=%cs")
        url = r["url"].split()[0].removesuffix(".git")
        mods, nbs = modules(base, r.get("index", [])), notebooks(base)
        by_col = defaultdict(list)                      # column -> [(table, use)]
        for u in usage:
            for x in u["uses"]:
                if x["repo"] == name:
                    by_col[u["column"]].append((u["table"], x))
        card = LIVE / "software" / "notes" / f"{name}.md"
        stem = f"Software - {name}"
        fm = ["---", f"title: {q(stem)}", "type: code-summary", f"created: {q(today())}",
              f"author: {q('generated by ' + SCRIPT)}", "tags: [Software]", f"repo: {name}",
              f"commit: {q(sha)}", f"commit_date: {q(date)}", f"url: {q(url)}", "generated: true", "---"]
        body = [f"> [!info] Generated on {today()} by `{SCRIPT}` from the checkout of {name} at its pin. "
                "Not written by an AI. Do not edit: rerun the script after the pin moves.", "",
                f"# {name}", "",
                (f"Code card (written by a member): [[{name}]]" if card.exists()
                 else f"No code card yet: a member can write `software/notes/{name}.md` from `templates/Code card.md`."), "",
                f"- **Repository:** {url}",
                f"- **Pinned commit:** [`{sha[:12]}`]({url}/tree/{sha}) of {date} (sources.yaml)",
                f"- **Licence:** {licence(base)}",
                f"- **Indexed for search:** {', '.join(f'`{x}`' for x in r.get('index', [])) or 'everything'}", ""]
        rd = readme_start(base)
        if rd:
            body += ["## From the README", "", rd, ""]
        if mods:
            body += [f"## Python modules ({len(mods)})", "", "| Module | What it says | Public names |", "|---|---|---|"]
            for m in mods:
                names = ", ".join(f"`{x}`" for x in m["public"][:8]) + (" …" if len(m["public"]) > 8 else "")
                body.append(f"| [`{m['file']}`]({url}/blob/{sha}/{m['file']}) | {cell(m['doc'][:120])} | {names} |")
            body.append("")
        if nbs:
            body += [f"## Notebooks ({len(nbs)})", ""]
            body += [f"- [`{n['file']}`]({url}/blob/{sha}/{n['file']}){' — ' + n['title'] if n['title'] else ''}" for n in nbs]
            body.append("")
        body += [f"## Gaia columns the code reads ({len(by_col)})", ""]
        if not by_col:
            body += ["None found (scripts/build/code_usage.py).", ""]
        else:
            body += ["Found by `scripts/build/code_usage.py`: a column name in a string, an attribute or "
                     "`table.column`. *Table not named* means the code never names the table, so the link "
                     "points to the main table with this column (gaia_source, else the shortest table name).", ""]
            for col in sorted(by_col):
                hits = by_col[col]
                named = sorted({t for t, x in hits if x["table_named"]})
                if named:
                    where = ", ".join(column_link(t, col, tables) for t in named)
                else:
                    cands = sorted({t for t, _ in hits})
                    main_t = "gaia_source" if "gaia_source" in cands else min(cands, key=lambda x: (len(x), x))
                    where = column_link(main_t, col, tables) + " *(table not named)*"
                spots = {(x["file"], x["cell"], x["line"]): x for _, x in hits}
                refs = []
                for (f, c, line), x in sorted(spots.items())[:3]:
                    link = f"{url}/blob/{sha}/{f}" + ("" if c else f"#L{line}")
                    refs.append(f"[`{f}`{(' ' + c) if c else f':{line}'}]({link})")
                more = f" (+{len(spots) - 3} more)" if len(spots) > 3 else ""
                body.append(f"- `{col}`: {where} — {', '.join(refs)}{more}")
            body.append("")
        (out_dir / f"{stem}.md").write_text("\n".join(fm + body) + "\n", encoding="utf-8")
        print(f"{stem}: {len(mods)} modules, {len(nbs)} notebooks, {len(by_col)} Gaia columns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
