#!/usr/bin/env python
"""Tests of scripts/build/gaia_docs.py on a small synthetic documentation site in the
LaTeXML layout of the Gaia documentation (no network):
- a data-model page -> columns with type and unit, a flag table kept as a Markdown table,
  the table note "<label> - <table>";
- a chapter page -> a section note with its parent, and a link to a column turned into
  the wikilink [[<label> - <table>#<column>]];
- the parsed columns checked against an archive column list (TAP), differences reported;
- the generated notes pass the checker.
Needs beautifulsoup4 (the knowledge base's environment). With --real, also checks the DR3
build in keeper/ if this machine has it.

    python scripts/test_build_docs.py [--real]
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILS: list[str] = []
BASE = "https://example.org/docs/"


def expect(name: str, ok: bool, detail="") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        print("     " + str(detail).strip().replace("\n", "\n     ")[:3000])


def page(up_href: str, up_title: str, tag: str, title: str, body: str, level: str = "section") -> str:
    return f"""<html><body><div class="ltx_page_main"><header class="ltx_page_header"><div>
<a href="{up_href}" title="{up_title}" class="ltx_ref" rel="up">up</a></div></header>
<div class="ltx_page_content"><section class="ltx_{level}">
<h1 class="ltx_title ltx_title_{level}"><span class="ltx_tag ltx_tag_{level}">{tag} </span>{title}</h1>
{body}</section></div></div></body></html>"""


SITE = {
    "index.html": '<html><body><div class="ltx_page_content"><h1 class="ltx_title">Documentation</h1>'
                  '<a href="Data_analysis/chap_nss/">7</a> <a href="Gaia_archive/chap_datamodel/sec_nss/">20.6</a>'
                  '</div></body></html>',
    "Data_analysis/chap_nss/index.html": page(
        "../../", "Gaia DR Documentation", "7", "Non-single stars",
        '<div class="ltx_para"><p class="ltx_p">The <a href="../../Gaia_archive/chap_datamodel/sec_nss/'
        'ssec_dm_orbits.html#orbits-period" class="ltx_ref">period</a> is fitted with '
        '<math alttext="P=2\\pi/n" display="inline"><mi>P</mi></math>.</p></div>', "chapter"),
    "Gaia_archive/chap_datamodel/index.html": page(
        "../../", "Part V Gaia archive ‣ Gaia DR Documentation", "20", "Datamodel description",
        '<div class="ltx_para"><p class="ltx_p">The tables.</p></div>', "chapter"),
    "Gaia_archive/chap_datamodel/sec_nss/index.html": page(
        "../", "Chapter 20 Datamodel description ‣ Part V Gaia archive ‣ Gaia DR Documentation",
        "20.6", "NSS tables", '<div class="ltx_para"><p class="ltx_p">Tables of binaries.</p></div>'),
    "Gaia_archive/chap_datamodel/sec_nss/ssec_dm_orbits.html": page(
        ".", "20.6 NSS tables ‣ Chapter 20 Datamodel description ‣ Part V Gaia archive ‣ Gaia DR Documentation",
        "20.6.1", '<span class="ltx_text ltx_font_smallcaps">orbits</span>',
        '<div class="ltx_para"><blockquote class="ltx_quote"><p class="ltx_p">Orbits of binaries.</p></blockquote></div>'
        '<div class="ltx_para"><p class="ltx_p"><span class="ltx_text ltx_font_bold">Columns description:</span></p></div>'
        '<div class="ltx_para"><p class="ltx_p"><span class="ltx_text ltx_font_bold ltx_font_smallcaps">period '
        '<a name="orbits-period" id="orbits-period" class="ltx_anchor"></a></span>: Orbital Period (double, Time[day])</p></div>'
        '<div class="ltx_para"><p class="ltx_p">Period of the orbit.</p></div>'
        '<div class="ltx_para"><p class="ltx_p"><span class="ltx_text ltx_font_bold ltx_font_smallcaps">flags '
        '<a name="orbits-flags" id="orbits-flags" class="ltx_anchor"></a></span>: Quality flag (long)</p></div>'
        '<figure class="ltx_table"><table class="ltx_tabular"><tr><td>Bit</td><td>Meaning</td></tr>'
        '<tr><td>0</td><td>No solution searched</td></tr><tr><td>6</td><td>RV available</td></tr></table>'
        '<figcaption class="ltx_caption">Table 20.1: flag bits</figcaption></figure>'),
}


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        root = tmp / "vault"
        (root / "scripts").mkdir(parents=True)
        for s in ("kb_common.py", "check_vault.py"):
            shutil.copy(REPO / "scripts" / s, root / "scripts")
        shutil.copytree(REPO / "scripts/build", root / "scripts/build")
        shutil.copytree(REPO / "templates", root / "templates")
        shutil.copy(REPO / "conventions.yaml", root)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "github.user", "keeper1"], check=True)
        (root / "sources.yaml").write_text(
            "repositories: []\ngaia:\n  - label: DR3\n    release: DR3\n    status: formal\n"
            "    doc_version: '1.3'\n    page: https://example.org\n    documentation:\n"
            f"      html: {BASE}\n      datamodel_path: Gaia_archive/chap_datamodel/\n"
            "    archive_columns:\n      tap: https://example.org/tap\n      query: x\n")
        snap = tmp / "documentation-html-2026-01-01.zip"
        manifest = {"start": BASE, "base": BASE, "fetched": "2026-01-01T00:00:00Z", "agent": "test",
                    "pages": {p: {"url": BASE + p, "sha256": "", "bytes": len(h)} for p, h in SITE.items()}}
        with zipfile.ZipFile(snap, "w") as z:
            for p, h in SITE.items():
                z.writestr(p, h)
            z.writestr("manifest.json", json.dumps(manifest))
        tapdir = root / "keeper/data/gaia/DR3"
        tapdir.mkdir(parents=True)
        (tapdir / "tap-columns-2026-01-01.csv").write_text(
            "table_name,column_name,datatype,unit,ucd,description\n"
            "gaiadr3.orbits,period,DOUBLE,d,,Orbital period\ngaiadr3.orbits,flags,BIGINT,,,Flags\n"
            "gaiadr3.orbits,extra_col,REAL,,,Only in the archive\n")

        r = subprocess.run([sys.executable, str(root / "scripts/build/gaia_docs.py"), "DR3", "--from", str(snap)],
                           cwd=root, capture_output=True, text=True)
        out = r.stdout + r.stderr
        expect("the build runs", r.returncode == 0, out)
        k = root / "keeper"
        cols = [json.loads(l) for l in open(k / "parsed/gaia/DR3/columns.jsonl")] if r.returncode == 0 else []
        by = {c["column"]: c for c in cols}
        expect("columns parsed with type and unit",
               by.get("period", {}).get("datatype") == "double" and by["period"]["unit"] == "day"
               and by.get("flags", {}).get("datatype") == "long", cols)
        expect("the flag table is kept as a Markdown table",
               "| 0 | No solution searched |" in by.get("flags", {}).get("description", ""), by.get("flags"))
        rep = json.loads((k / "parsed/gaia/DR3/parse_report.json").read_text()) if r.returncode == 0 else {}
        expect("checked against the archive: extra_col is only in the archive",
               rep.get("tables_with_column_differences", {}).get("orbits", {}).get("only_in_tap") == ["extra_col"], rep)
        note = k / "generated/gaia/DR3/datamodel/DR3 - orbits.md"
        expect("the table note exists, with a link to the online page",
               note.exists() and f"{BASE}Gaia_archive/chap_datamodel/sec_nss/ssec_dm_orbits.html" in note.read_text(), out)
        chap = list((k / "generated/gaia/DR3/documentation").rglob("DR3 doc - 7 - Non-single stars.md"))
        text = chap[0].read_text() if chap else ""
        expect("the chapter note links to the column as [[DR3 - orbits#period|period]], with its math",
               "[[DR3 - orbits#period|period]]" in text and "$P=2\\pi/n$" in text, text)
        sec = list((k / "generated/gaia/DR3/documentation").rglob("DR3 doc - 20.6 - NSS tables.md"))
        expect("a section note names its parent page",
               sec and "Part of [[DR3 doc - 20 - Datamodel description]]" in sec[0].read_text(),
               sec[0].read_text() if sec else "")
        c = subprocess.run([sys.executable, str(root / "scripts/check_vault.py")], cwd=root, capture_output=True, text=True)
        expect("the generated notes pass the checker", c.returncode == 0, c.stdout + c.stderr)

    if "--real" in sys.argv:
        k = REPO / "keeper/parsed/gaia/DR3"
        if not (k / "columns.jsonl").exists():
            print("SKIP the real DR3 build: keeper/parsed/gaia/DR3/ is not on this machine")
        else:
            cols = {f"{c['table']}.{c['column']}": c for c in map(json.loads, open(k / "columns.jsonl"))}
            p = cols.get("nss_two_body_orbit.period", {})
            expect("DR3: nss_two_body_orbit.period is a double in days",
                   (p.get("datatype"), p.get("unit")) == ("double", "day"), p)
            expect("DR3: the flags table of nss_two_body_orbit is a Markdown table",
                   "| 8 | BAD_UNCHECKED_NUMBER_OF_TRANSITS |" in cols.get("nss_two_body_orbit.flags", {}).get("description", ""))
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
