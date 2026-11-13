#!/usr/bin/env python
"""Tests of the section detection and the title line of paper passages (kb_pkg/chunk.py):
- "3. Title" and "3.2. Title" are headings; a subsection is named with its section;
- footnotes ("3 The value ...") and numbered list items (a full line that goes on in lower
  case) are not headings;
- one missed heading does not stop the count; "Appendix A: Title" is a section;
- each passage starts with "<paper title> — <section>" and carries the section.
Needs the knowledge base's environment (kb_pkg imports pymupdf).

    python scripts/test_paper_sections.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kb_pkg import chunk  # noqa: E402

FAILS = []


def expect(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        print("     " + str(detail)[:2000])


PAGES = [(1, "A paper about orbits\nAbstract text here.\n1. Introduction\nBinaries are common.\n"
             "3 The value is taken from the archive\n2. Method\n2.1. The orbit model\nWe fit orbits.\n"
             "The steps are:\n3. Calculate a primary solution by simultaneously estimating\nthe attitude and the sources.\n"),
         (2, "4. Results\nThe orbits are good.\n4.2. Periods\nPeriods are long.\nAppendix A: Extra tables\nA table.\n")]


def main() -> int:
    tg = chunk.paper_sections(PAGES)
    sec = {}
    for w, _, s in tg:
        sec.setdefault(w, s)
    expect("text before the first heading has no section", sec["Abstract"] == "")
    expect("a numbered heading starts a section", sec["Binaries"] == "1. Introduction", sec["Binaries"])
    expect("a footnote is not a heading", sec["value"] == "1. Introduction", sec["value"])
    expect("a subsection is named with its section", sec["fit"] == "2. Method / 2.1. The orbit model", sec["fit"])
    expect("a numbered list item is not a heading", sec["attitude"] == "2. Method / 2.1. The orbit model", sec["attitude"])
    expect("a missed heading (3.) does not stop the count", sec["good."] == "4. Results", sec["good."])
    expect("an appendix is a section", sec["table."] == "Appendix A: Extra tables", sec["table."])
    cs = chunk.chunk_paper("Doe et al (2025) - Orbits of binaries", PAGES, words=12, overlap=0)
    expect("each passage starts with the paper title", all(c.text.startswith("Orbits of binaries") for c in cs), cs[0].text)
    last = cs[-1]
    expect("a passage carries its section, in the text and in the record",
           last.section == "Appendix A: Extra tables" and "— Appendix A: Extra tables\n" in last.text, (last.section, last.text))
    # Headings recorded from the fonts of a PDF (scripts/build/paper_text.py)
    import pymupdf
    sys.path.insert(0, str(Path(__file__).resolve().parent / "build"))
    import paper_text
    doc = pymupdf.open()
    page, y = doc.new_page(), 60

    def put(text, font="tiro", size=10):
        nonlocal y
        page.insert_text((60, y), text, fontname=font, fontsize=size)
        y += 16
    put("1. Introduction", "hebo", 10.4)
    put("Binaries are common in the Galaxy and many are found.")
    put("2. Method and the long name of this section which runs", "hebo", 10.4)
    put("over two lines", "hebo", 10.4)
    put("The steps are:")
    put("3. Calculate a primary solution by estimating all")              # a list item: body font
    put("the parameters.")
    put("1. Completeness.", "heit", 10)                                    # a run-in title: not the main font
    put("2.1. The orbit model", "heit", 9.5)
    put("We fit orbits.")
    for _ in range(8):                                                     # body text is most of a paper
        put("More text of the body, set in the serif font of the paper, line after line.")
    put("3. Results", "hebo", 10.4)
    put("3.1. Periods", "heit", 9.5)
    put("5.1. A stray number", "heit", 9.5)                                # no section 5 is open
    put("Appendix A: Extra tables", "hebo", 10.4)
    hs = paper_text.headings(doc)[0]
    titles = [(h["title"], h["level"]) for h in hs]
    expect("headings are told by font: sections, subsections and the appendix, nothing else",
           titles == [("1. Introduction", 1), ("2. Method and the long name of this section which runs over two lines", 1),
                      ("2.1. The orbit model", 2), ("3. Results", 1), ("3.1. Periods", 2), ("Appendix A: Extra tables", 1)], titles)
    text = page.get_text("text")
    tg = chunk.paper_sections([(1, text)], {1: hs})
    sec = {}
    for w, _, s in tg:
        sec.setdefault(w, s)
    expect("with recorded headings, a numbered list item stays in its section",
           sec["parameters."].startswith("2. Method and the long name"), sec["parameters."])
    expect("a subsection is named with its section (recorded headings)",
           sec["fit"] == "2. Method and the long name of this section which runs over two lines / 2.1. The orbit model", sec["fit"])
    expect("the heading's own words are not repeated in the passage text",
           "Introduction" not in sec and "lines" not in sec, sorted(sec)[:8])
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
