#!/usr/bin/env python
"""Build a Gaia release's HTML documentation (index keeper only), e.g. DR3.

For one `gaia:` entry of sources.yaml with `documentation: html:`:
  1. snapshot  the documentation website into keeper/data/gaia/<label>/documentation-html-<date>.zip
               (--snapshot; otherwise the newest snapshot there is used, with no network);
  2. archive   the archive's own column list (TAP schema) into keeper/data/gaia/<label>/
               tap-columns-<date>.csv (--tap; otherwise the newest one is used);
  3. data model the data-model chapter -> keeper/parsed/gaia/<label>/columns.jsonl, tables.jsonl,
               checked against the TAP column list (parse_report.json), and one generated note
               per table, "<label> - <table>" (as for the PDF data models);
  4. sections  every other page -> keeper/parsed/gaia/<label>/sections.jsonl and one generated
               note per page, "<label> doc - <section> - <title>", in
               keeper/generated/gaia/<label>/documentation/<part>/<chapter>/.
Links between pages become wikilinks; links to a column become [[<label> - <table>#<column>]].

    python scripts/build/gaia_docs.py DR3 [--snapshot] [--tap] [--from <snapshot zip>]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urljoin

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kb_common import KEEPER, ROOT, github_user, today  # noqa: E402

import datamodel_pdf  # noqa: E402  (last_paren, split_type, typed)
import gaia_datamodel as gdm  # noqa: E402  (lock, sha256, write_notes, q)
import html_snapshot  # noqa: E402
import latexml_md as L  # noqa: E402

SCRIPT = "scripts/build/gaia_docs.py"
FORBIDDEN = re.compile(r'[:?*"<>|^#\[\]/\\]')


def entry(label: str) -> dict:
    for e in yaml.safe_load((ROOT / "sources.yaml").read_text()).get("gaia", []):
        if e.get("label") == label:
            if "documentation" not in e or "html" not in e["documentation"]:
                sys.exit(f"sources.yaml: '{label}' has no documentation: html: entry")
            return e
    sys.exit(f"sources.yaml: no gaia entry with label '{label}'")


def newest(folder: Path, pattern: str) -> Path | None:
    files = sorted(folder.glob(pattern))
    return files[-1] if files else None


# ---- 1, 2: snapshots ---------------------------------------------------------------------

def get_snapshot(e: dict, folder: Path, take: bool, local: Path | None, user: str) -> Path:
    if local:
        fetched = html_snapshot.read(local)[0]["fetched"][:10]
        dest = folder / f"documentation-html-{fetched}.zip"
        if not dest.exists():
            shutil.copy(local, dest)
        gdm.lock(dest, user, f"snapshot of {e['documentation']['html']} (copied from {local.name})")
        return dest
    if take:
        dest = folder / f"documentation-html-{today()}.zip"
        if dest.exists():
            sys.exit(f"{dest.name} exists already: one snapshot per day")
        print(f"snapshot of {e['documentation']['html']} (about 650 pages, 0.5 s apart) ...")
        html_snapshot.snapshot(e["documentation"]["html"], dest)
        gdm.lock(dest, user, f"snapshot of {e['documentation']['html']}")
        return dest
    z = newest(folder, "documentation-html-*.zip")
    if not z:
        sys.exit(f"no snapshot in keeper/{folder.relative_to(KEEPER)}: run with --snapshot")
    gdm.lock(z, user, f"snapshot of {e['documentation']['html']}")
    return z


def get_tap(e: dict, folder: Path, take: bool, user: str) -> Path | None:
    spec = e.get("archive_columns")
    if take:
        if not spec:
            sys.exit("sources.yaml: no archive_columns: entry")
        url = spec["tap"].rstrip("/") + "/sync?" + urllib.parse.urlencode(
            {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": spec["query"]})
        dest = folder / f"tap-columns-{today()}.csv"
        if not dest.exists():
            req = urllib.request.Request(url, headers={"User-Agent": html_snapshot.AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                dest.write_bytes(r.read())
        gdm.lock(dest, user, spec["tap"] + " : " + spec["query"])
        return dest
    f = newest(folder, "tap-columns-*.csv")
    if f:
        gdm.lock(f, user, (spec or {}).get("tap", "TAP"))
    return f


# ---- page model --------------------------------------------------------------------------

class Page:
    def __init__(self, path: str, html: bytes, base: str):
        self.path, self.base = path, base
        self.url = base + (path[:-len("index.html")] if path.endswith("index.html") else path)
        self.soup = L.soup(html)
        h = self.soup.find(["h1", "h2"], class_=re.compile("ltx_title"))
        tag = h.find(class_=re.compile("ltx_tag")) if h else None
        self.tag = re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).rstrip(".") if tag else ""
        if tag:
            tag.extract()
        self.title = re.sub(r"\s+", " ", h.get_text(" ", strip=True)) if h else Path(path).stem
        up = self.soup.find("a", rel="up")
        self.up_href = up.get("href") if up else None
        crumbs = [c.strip() for c in (up.get("title") or "").split("‣")] if up else []
        self.chapter = next((c for c in crumbs if c.startswith("Chapter")), "")
        self.part = next((c for c in crumbs if c.startswith("Part")), "")
        if self.title.startswith("Chapter") or not self.chapter and self.tag.isdigit():
            self.chapter = f"Chapter {self.tag} {self.title}".strip()
        self.content = self.soup.find(class_="ltx_page_content") or self.soup.body

    def target(self, href: str) -> tuple[str, str]:
        """(page path, anchor) of a link on this page."""
        url = urljoin(self.url, href)
        if not url.startswith(self.base):
            return "", ""
        rel, _, anchor = url[len(self.base):].partition("#")
        return (rel + "index.html" if rel == "" or rel.endswith("/") else rel), anchor


def stem_for(label: str, p: Page) -> str:
    title = FORBIDDEN.sub("_", p.title).strip()[:90]
    return f"{label} doc - {p.tag} - {title}" if p.tag else f"{label} doc - {title}"


# ---- 3: data model -----------------------------------------------------------------------

def parse_table_page(e: dict, p: Page, resolve) -> tuple[dict, list[dict]] | None:
    """(table record, column records) of a data-model page, or None if it lists no columns."""
    name = p.title.strip()
    anchors = p.content.find_all("a", class_="ltx_anchor", id=re.compile("^" + re.escape(name) + "-"))
    if not anchors:
        return None
    heads = {}
    for a in anchors:
        para = a.find_parent("div", class_="ltx_para") or a.find_parent("p")
        heads[id(para)] = (para, a["id"][len(name) + 1:])
    section = p.content.find("section") or p.content
    table = {"table": name, "group": p.up_title if hasattr(p, "up_title") else "", "section": p.tag,
             "access": "", "url": p.url, "page_start": None, "description": ""}
    cols, desc, cur = [], [], None
    for block in section.children:
        if not getattr(block, "name", None) or block.name in ("h1", "h2", "h3") \
                or "ltx_date" in L.classes(block):
            continue
        if id(block) in heads:
            para, colname = heads[id(block)]
            header = re.sub(r"\s+", " ", L.inline(para)).replace("**", "").strip()
            _, _, rest = header.partition(":")
            parsed = datamodel_pdf.last_paren(rest.strip())
            cur = {"release": e["release"], "label": e["label"], "status": e.get("status", "formal"),
                   "doc_version": e["doc_version"], "group": table["group"], "table": name,
                   "column": colname, "position": len(cols) + 1, "short_description": rest.strip(),
                   "datatype": None, "quantity": None, "unit": None, "description": "",
                   "page_start": None, "page_end": None, "url": f"{p.url}#{name}-{colname}",
                   "has_embedded_table": False, "embedded_table_pages": [], "header": header}
            if parsed and datamodel_pdf.TYPE_WORD.match(parsed[1]):
                cur["short_description"] = parsed[0]
                cur.update(datamodel_pdf.split_type(parsed[1]))
            cols.append(cur)
            continue
        md = L.element(block, resolve)
        if not md.strip() or "Columns description" in md:
            continue
        if cur is None:
            desc.append(md)
        else:
            cur["description"] = (cur["description"] + "\n\n" + md).strip()
    table["description"] = "\n\n".join(d.lstrip("> ").strip() for d in desc).strip()
    table["n_columns"] = len(cols)
    return table, cols


def tap_columns(path: Path | None) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    if path:
        for r in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
            t = r["table_name"].split(".", 1)[-1].lower()
            out[t][r["column_name"].lower()] = r
    return out


# ---- 4: notes ----------------------------------------------------------------------------

def section_note(e: dict, p: Page, stem: str, parent: str | None, body: str, source: str) -> str:
    tags = ["Gaia"] + (["NSS"] if "cu4nss" in p.path or "non-single" in p.title.lower() else [])
    fm = ["---", f"title: {gdm.q(stem)}", "type: gaia-section", f"created: {gdm.q(today())}",
          f"author: {gdm.q('generated by ' + SCRIPT)}", "tags: [" + ", ".join(tags) + "]",
          f"release: {e['release']}", f"release_status: {e.get('status', 'formal')}",
          f"doc_version: {gdm.q(e['doc_version'])}", f"section: {gdm.q(p.tag)}",
          f"chapter: {gdm.q(p.chapter)}", f"part: {gdm.q(p.part)}", f"url: {gdm.q(p.url)}",
          "generated: true", f"source: {gdm.q(source)}", "---"]
    head = [f"> [!info] Generated on {today()} by `{SCRIPT}` from {source}: the documentation's own "
            "text, converted by script, not written by an AI. Do not edit: rerun the script.", "",
            f"# {(p.tag + ' ') if p.tag else ''}{p.title}", "",
            " · ".join(x for x in [f"Part of [[{parent}]]" if parent else "", p.chapter, p.part,
                                   f"[online]({p.url})"] if x), ""]
    return "\n".join(fm + head + [body, ""])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("label")
    ap.add_argument("--snapshot", action="store_true", help="take a new snapshot of the website")
    ap.add_argument("--from", dest="local", type=Path, help="use this snapshot zip (copied into keeper/)")
    ap.add_argument("--tap", action="store_true", help="fetch the archive's column list again")
    a = ap.parse_args()
    e, user = entry(a.label), github_user()
    label = e["label"]
    folder = KEEPER / "data" / "gaia" / label
    folder.mkdir(parents=True, exist_ok=True)
    zpath = get_snapshot(e, folder, a.snapshot, a.local.expanduser() if a.local else None, user)
    tap_path = get_tap(e, folder, a.tap, user)
    manifest, html = html_snapshot.read(zpath)
    base = manifest["base"]
    source = f"the {label} documentation {e['doc_version']}, snapshot {manifest['fetched'][:10]} of {base}"

    pages = {path: Page(path, data, base) for path, data in html.items() if path.endswith(".html")}
    titles = {path: pg.title for path, pg in pages.items()}
    for pg in pages.values():
        if pg.up_href:
            up_path, _ = pg.target(pg.up_href)
            pg.up_title = titles.get(up_path, "")

    dm_prefix = e["documentation"].get("datamodel_path", "Gaia_archive/chap_datamodel/")
    stems: dict[str, str] = {}
    table_pages: dict[str, str] = {}                 # page path -> table name
    for path, pg in pages.items():
        if path.startswith(dm_prefix) and path.endswith(".html") and Path(path).name.startswith("ssec_dm_"):
            table_pages[path] = pg.title.strip()
            stems[path] = f"{label} - {pg.title.strip()}"
    used = Counter()
    for path, pg in sorted(pages.items()):
        if path in stems:
            continue
        s = stem_for(label, pg)
        used[s] += 1
        stems[path] = s if used[s] == 1 else f"{s} ({used[s]})"

    def resolver(pg: Page):
        def resolve(href: str) -> str | None:
            path, anchor = pg.target(href)
            if path not in stems:
                return None
            if path in table_pages and anchor.startswith(table_pages[path] + "-"):
                return f"{stems[path]}#{anchor[len(table_pages[path]) + 1:]}"
            return stems[path]
        return resolve

    # data model
    tables, columns, empty = [], [], []
    for path in sorted(table_pages, key=lambda p: [int(x) if x.isdigit() else x
                                                   for x in re.split(r"[.]", pages[p].tag)]):
        got = parse_table_page(e, pages[path], resolver(pages[path]))
        if got:
            tables.append(got[0])
            columns += got[1]
        else:
            empty.append(path)
            del stems[path]
    tap = tap_columns(tap_path)
    doc_cols = defaultdict(set)
    for c in columns:
        doc_cols[c["table"].lower()].add(c["column"].lower())
    only_docs = sorted(set(doc_cols) - set(tap)) if tap else []
    only_tap = sorted(set(tap) - set(doc_cols)) if tap else []
    col_diff = {t: {"only_in_docs": sorted(doc_cols[t] - set(tap[t])), "only_in_tap": sorted(set(tap[t]) - doc_cols[t])}
                for t in sorted(set(doc_cols) & set(tap)) if doc_cols[t] != set(tap[t])}
    for c in columns:                                # the archive's own record, beside the documentation's
        r = tap.get(c["table"].lower(), {}).get(c["column"].lower())
        if r:
            c["archive"] = {"datatype": r.get("datatype"), "unit": r.get("unit") or None,
                            "ucd": r.get("ucd") or None, "description": r.get("description")}
    unit_notation = sum(1 for c in columns if "archive" in c and (c["unit"] or "") != (c["archive"]["unit"] or ""))
    untyped = [c["header"] for c in columns if not c["datatype"]]
    dup = [f"{t}.{c}" for (t, c), n in Counter((c["table"], c["column"]) for c in columns).items() if n > 1]
    report = {"source": source, "release": e["release"], "label": label, "status": e.get("status", "formal"),
              "doc_version": e["doc_version"], "pages": len(pages), "tables_found": len(tables),
              "columns": len(columns), "table_pages_without_columns": empty, "duplicate_columns": dup,
              "headers_without_type": untyped, "tap_file": tap_path.name if tap_path else None,
              "tap_tables": len(tap), "tables_only_in_docs": only_docs, "tables_only_in_tap": only_tap,
              "tables_with_column_differences": col_diff}
    n_diff = sum(len(v["only_in_docs"]) + len(v["only_in_tap"]) for v in col_diff.values())
    report["checks"] = [
        f"- Data-model pages without column entries: {len(empty)}",
        f"- Duplicate column names: {len(dup)}",
        f"- Column headers without a parsed type: {len(untyped)}",
        (f"- Against the archive's column list ({tap_path.name}, {len(tap)} tables): "
         f"{len(only_docs)} tables only in the documentation, {len(only_tap)} only in the archive, "
         f"{len(col_diff)} tables whose columns differ ({n_diff} columns); units written differently "
         f"(e.g. `day` / `d`) for {unit_notation} columns: each column record keeps both") if tap else
        "- Not checked against the archive's column list (run with --tap)",
    ]
    for c in columns:
        c.pop("header", None)

    pdir = KEEPER / "parsed" / "gaia" / label
    datamodel_pdf.write(pdir, tables, columns, report)
    gdm.write_notes(e, tables, columns, report, source)

    # sections
    ddir = KEEPER / "generated" / "gaia" / label / "documentation"
    if ddir.exists():
        shutil.rmtree(ddir)
    sections = []
    for path, pg in sorted(pages.items()):
        if path in table_pages:
            continue
        resolve = resolver(pg)
        body = L.markdown(pg.content, resolve)
        body = re.sub(r"^#+ .*\n+", "", body, count=1)          # the page title is written above
        parent = None
        if pg.up_href:
            up_path, _ = pg.target(pg.up_href)
            parent = stems.get(up_path)
        parts = Path(path).parts
        sub = Path(*parts[:2]) if len(parts) > 2 else Path(parts[0]) if len(parts) > 1 else Path(".")
        out = ddir / sub / f"{stems[path]}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(section_note(e, pg, stems[path], parent, body, source), encoding="utf-8")
        sections.append({"section": pg.tag, "title": pg.title, "chapter": pg.chapter, "part": pg.part,
                         "url": pg.url, "note": stems[path], "path": path, "chars": len(body)})
    with open(pdir / "sections.jsonl", "w") as fh:
        for s in sections:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    short = {k: (v if not isinstance(v, (list, dict)) or len(v) < 6 else f"{len(v)} items")
             for k, v in report.items() if k != "checks"}
    print(json.dumps(short, indent=1, ensure_ascii=False))
    print(f"{len(tables)} table notes, {len(sections)} section notes -> keeper/generated/gaia/{label}/")
    return 1 if (empty or dup) else 0


if __name__ == "__main__":
    sys.exit(main())
