#!/usr/bin/env python
"""Build a Gaia data model from its public source (index keeper only).

For one `gaia:` entry of sources.yaml that has a `datamodel:` (a zip with the PDF):
  1. fetch    the zip from its URL (or --from a local copy), check its SHA-256 against
              sources.yaml, keep it and its files in keeper/data/gaia/<label>/, with locks;
  2. parse    the PDF into keeper/parsed/gaia/<label>/ (columns.jsonl, tables.jsonl,
              parse_report.json): the records lookup_column and find_columns answer from;
  3. notes    one generated note per table, and a hub note, in
              keeper/generated/gaia/<label>/datamodel/ ("<label> - <table>.md").

A draft (status: draft) is marked as such in every record and note. When the formal
release arrives: add its entry to sources.yaml, build it, then remove the draft entry
and its three folders.

    python scripts/build/gaia_datamodel.py DR4-draft [--from ~/Downloads/<zip>] [--no-find-tables]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_common import KEEPER, ROOT, github_user, today  # noqa: E402

import datamodel_pdf  # noqa: E402  (same folder)

SCRIPT = "scripts/build/gaia_datamodel.py"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def entry(label: str) -> dict:
    for e in yaml.safe_load((ROOT / "sources.yaml").read_text()).get("gaia", []):
        if e.get("label") == label:
            if "datamodel" not in e:
                sys.exit(f"sources.yaml: '{label}' has no datamodel: entry")
            return e
    sys.exit(f"sources.yaml: no gaia entry with label '{label}'")


def lock(file: Path, user: str, source: str) -> str:
    """Write or check keeper/locks/<path>.json. Returns 'new', 'same'; exits on a mismatch."""
    rel = file.relative_to(KEEPER).as_posix()
    lf = KEEPER / "locks" / (rel + ".json")
    digest = sha256(file)
    if lf.exists():
        old = json.loads(lf.read_text())
        if old.get("sha256") != digest:
            sys.exit(f"keeper/{rel} differs from its lock: someone changed it; check before rebuilding")
        return "same"
    lf.parent.mkdir(parents=True, exist_ok=True)
    lf.write_text(json.dumps({"path": rel, "size": file.stat().st_size, "sha256": digest,
                              "added_by": user, "added": today(), "source": source}, indent=1) + "\n")
    return "new"


def fetch(e: dict, local: Path | None, user: str) -> Path:
    """The data-model PDF in keeper/data/gaia/<label>/, fetched and checked."""
    dm = e["datamodel"]
    folder = KEEPER / "data" / "gaia" / e["label"]
    folder.mkdir(parents=True, exist_ok=True)
    zpath = folder / Path(dm["zip"]).name
    if not zpath.exists():
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t) / zpath.name
            if local:
                shutil.copy(local, tmp)
                how = f"local copy {local.name}, identical to {dm['zip']}"
            else:
                print(f"downloading {dm['zip']}")
                urllib.request.urlretrieve(dm["zip"], tmp)
                how = dm["zip"]
            if sha256(tmp) != dm["sha256"]:
                sys.exit(f"SHA-256 of {tmp.name} is not the one in sources.yaml: not the published file")
            shutil.move(tmp, zpath)
        print(f"stored keeper/{zpath.relative_to(KEEPER)} ({how})")
    elif sha256(zpath) != dm["sha256"]:
        sys.exit(f"keeper/{zpath.relative_to(KEEPER)} is not the file in sources.yaml")
    lock(zpath, user, dm["zip"])
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if "/" in name or name.startswith("."):
                continue                          # only top-level files; no paths from the archive
            out = folder / name
            if not out.exists():
                out.write_bytes(z.read(name))
            lock(out, user, f"{dm['zip']} ({name})")
    pdf = folder / dm["pdf"]
    if not pdf.exists():
        sys.exit(f"{dm['pdf']} is not in the zip")
    return pdf


# ---- generated notes ---------------------------------------------------------------------

def md_text(s: str) -> str:
    out = []
    for line in s.split("\n"):
        line = line.strip()
        line = re.sub(r"<(?=[A-Za-z/])", "&lt;", line)
        if line.startswith("• "):
            line = "- " + line[2:]
        elif line.startswith("– "):
            line = "    - " + line[2:]
        elif line.startswith("#"):
            line = "\\" + line
        out.append(line)
    merged: list[str] = []
    for line in out:                                 # keep list items together
        if merged and line.lstrip().startswith("- ") and merged[-1].split("\n")[-1].lstrip().startswith("- "):
            merged[-1] += "\n" + line
        else:
            merged.append(line)
    return "\n\n".join(merged)


def cell(s) -> str:
    return (str(s) if s not in (None, "") else "").replace("|", "\\|").replace("\n", " ")


def pages(a, b) -> str:
    return f"{a}" if a == b else f"{a}–{b}"


def q(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def where(x: dict, first: int | None = None, last: int | None = None) -> str:
    """'PDF p. 814–822' for a PDF data model, a link for an HTML one."""
    if x.get("url"):
        return f"[documentation]({x['url']})"
    a = first if first is not None else x["page_start"]
    b = last if last is not None else x.get("page_end", a)
    return f"PDF p. {pages(a, b)}"


def check_lines(report: dict) -> list[str]:
    """The parse checks shown on the hub note."""
    if "checks" in report:
        return report["checks"]
    return [f"- Tables in the outline but not found: {len(report['tables_missing'])}",
            f"- Tables with no columns: {len(report['tables_without_columns'])}",
            f"- Duplicate column names: {len(report['duplicate_columns'])}",
            f"- Column headers without a parsed type: {len(report['unparsed_headers'])}"
            + "".join(f"\n    - {h}" for h in report["unparsed_headers"]),
            f"- Columns whose description contains an embedded table: {report['columns_with_embedded_table']}"
            + ("" if report["find_tables_run"] else " (table detection not run)")]


def write_notes(e: dict, tables: list[dict], columns: list[dict], report: dict, source: str) -> Path:
    label, status, doc_version = e["label"], e.get("status", "formal"), e["doc_version"]
    ndir = KEEPER / "generated" / "gaia" / label
    tdir = ndir / "datamodel"
    tdir.mkdir(parents=True, exist_ok=True)
    for old in tdir.glob("*.md"):
        old.unlink()
    by = defaultdict(list)
    for c in columns:
        by[c["table"]].append(c)
    compare = {}
    dr3 = KEEPER / "parsed" / "gaia" / "DR3" / "columns.jsonl"
    if label != "DR3" and dr3.exists():
        for l in open(dr3):
            c = json.loads(l)
            compare.setdefault(c["table"], set()).add(c["column"])
    hub = f"{label} data model"
    draft = ([f"> [!warning] Draft. ESA's preliminary data model ({doc_version}); names, types and "
              f"units may change. To be replaced by {e.get('replaced_by', 'the formal release')}.", ""]
             if status == "draft" else [])
    made = (f"> [!info] Generated on {today()} by `{SCRIPT}` from {source}. The text is the "
            "document's own wording, extracted by script, not written by an AI. Do not edit: rerun the script.")

    for t in tables:
        name, cs = t["table"], by[t["table"]]
        loc = where(t) if t.get("url") else where(t, t["page_start"],
                                                  max(c["page_end"] for c in cs) if cs else t["page_start"])
        tags = ["Gaia", "DataModel"] + (["NSS"] if name.startswith("nss_") else [])
        emb = [c for c in cs if c["has_embedded_table"]]
        fm = ["---", f"title: {q(f'{label} - {name}')}", "type: gaia-table", f"created: {q(today())}",
              f"author: {q('generated by ' + SCRIPT)}", "tags: [" + ", ".join(tags) + "]",
              f"release: {e['release']}", f"release_status: {status}", f"doc_version: {q(doc_version)}",
              "generated: true", f"table: {name}", f"group: {q(t['group'])}", f"section: {q(t['section'] or '')}",
              f"access: {q(t.get('access') or '')}", f"where: {q(loc)}", f"n_columns: {len(cs)}",
              f"source: {q(source)}", "---"]
        body = [made, ""] + draft
        if emb:
            body += ["> [!warning] Embedded tables. The descriptions of "
                     + ", ".join(f"`{c['column']}` (p. {', '.join(map(str, c['embedded_table_pages']))})" for c in emb)
                     + " contain a table or formula that text extraction garbles. Read those pages in the PDF.", ""]
        body += [f"# {name}", "", f"Part of [[{hub}]] · group: {t['group']} · section {t['section'] or '—'} · "
                 f"access: {t.get('access') or '—'} · {len(cs)} columns · {loc}", ""]
        if t["description"].strip():
            body += ["## Description", "", md_text(t["description"]), ""]
        if compare:
            if name in compare:
                new = sorted({c["column"] for c in cs} - compare[name])
                gone = sorted(compare[name] - {c["column"] for c in cs})
                body += ["## Changes from DR3", "", "Compared by column name; a renamed column shows as one "
                         "removal and one addition.", "",
                         f"- **New in {label}** ({len(new)}): " + (", ".join(f"`{x}`" for x in new) or "none"),
                         f"- **Not in {label}** ({len(gone)}): " + (", ".join(f"`{x}`" for x in gone) or "none"), ""]
            else:
                body += ["## Changes from DR3", "", "New table: not in DR3.", ""]
        body += ["## Columns", "", "| # | Column | Type | Unit | Short description |", "|---|---|---|---|---|"]
        for c in cs:
            unit = f"{c['quantity'] or ''} [{c['unit']}]" if c["unit"] else (c["quantity"] or "")
            body.append(f"| {c['position']} | [[#{c['column']}\\|{c['column']}]] | {cell(c['datatype'])} | "
                        f"{cell(unit)} | {cell(c['short_description'])} |")
        body += ["", "## Column details", ""]
        for c in cs:
            unit = f"{c['quantity'] or ''} [{c['unit']}]".strip() if c["unit"] else (c["quantity"] or "—")
            body += [f"### {c['column']}", "",
                     f"**{c['short_description']}** · type: `{c['datatype']}` · unit: {unit} · "
                     f"{where(c)}"
                     + (" · ⚠ contains a table or formula, read the PDF" if c["has_embedded_table"] else ""), ""]
            if c["description"].strip():
                body += [md_text(c["description"]), ""]
        (tdir / f"{label} - {name}.md").write_text("\n".join(fm + body) + "\n", encoding="utf-8")

    groups = defaultdict(list)
    for t in tables:
        groups[t["group"]].append(t)
    lines = ["---", f"title: {q(hub)}", "type: hub", f"created: {q(today())}", f"author: {q('generated by ' + SCRIPT)}",
             "tags: [Gaia, DataModel]", f"release: {e['release']}", f"release_status: {status}",
             f"doc_version: {q(doc_version)}", "generated: true", f"source: {q(source)}", "---",
             made, ""] + draft + [
             f"# {hub}", "",
             f"Source: {source}. Parsed: {report['tables_found']} tables, {report['columns']} columns.", "",
             "## Parse checks", ""] + check_lines(report) + ["", "## Tables", ""]
    for g, ts in groups.items():
        lines += [f"### {g}", ""]
        for t in ts:
            lines.append(f"- [[{label} - {t['table']}|{t['table']}]] — {t['n_columns']} columns")
        lines.append("")
    (ndir / f"{hub}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ndir


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("label", help="label of a gaia: entry in sources.yaml, e.g. DR4-draft")
    ap.add_argument("--from", dest="local", type=Path, help="a local copy of the zip (checked against the SHA-256)")
    ap.add_argument("--no-find-tables", action="store_true", help="skip embedded-table detection (faster)")
    a = ap.parse_args()
    e = entry(a.label)
    user = github_user()
    pdf = fetch(e, a.local.expanduser() if a.local else None, user)
    print(f"parsing {pdf.name} ...")
    tables, columns, report = datamodel_pdf.parse(pdf, release=e["release"], doc_version=e["doc_version"],
                                                  label=e["label"], status=e.get("status", "formal"),
                                                  find_tables=not a.no_find_tables)
    pdir = KEEPER / "parsed" / "gaia" / e["label"]
    datamodel_pdf.write(pdir, tables, columns, report)
    source = f"{e['datamodel']['zip'].rsplit('/', 1)[-1]} ({e['page']})"
    ndir = write_notes(e, tables, columns, report, source)
    short = {k: (v if not isinstance(v, list) or len(v) < 6 else f"{len(v)} items") for k, v in report.items()}
    print(json.dumps(short, indent=1, ensure_ascii=False))
    print(f"parsed -> keeper/{pdir.relative_to(KEEPER)}; {len(tables)} table notes and the hub -> "
          f"keeper/{ndir.relative_to(KEEPER)}")
    bad = report["tables_missing"] or report["tables_without_columns"] or report["duplicate_columns"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
