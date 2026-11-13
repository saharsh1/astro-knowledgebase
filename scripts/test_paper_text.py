#!/usr/bin/env python
"""Tests of scripts/build/paper_text.py (the cleaning of paper text) and of the paper names
made by scripts/ingest_paper.py. Standard library and PyYAML only.

    python scripts/test_paper_text.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "build"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest_paper as ingest  # noqa: E402
import paper_text  # noqa: E402

FAILS: list[str] = []


def expect(name: str, ok: bool, detail="") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        print("     " + str(detail)[:2000])


def main() -> int:
    body = ("1. Introduction\nThe orbital period and the orbi-\ntal phase of a two-\nbody system. The ﬂag "
            "bits are listed. We ﬁt the orbit.\n" * 30)
    pages = [body, body, "Conclusions\nDone.\nReferences\nArenou, F. 2023, A&A, 674, A34\n"
             "Halbwachs, J.-L. 2023, A&A, 674, A9\nAppendix A: The bit_index table\nbit 0 is ra.\n"]
    out, ranges, s = paper_text.clean(pages)
    expect("ligatures replaced and counted", "flag bits" in out[0] and "We fit" in out[0] and s["ligatures"] == 120, s)
    expect("a split word that occurs whole elsewhere is joined", "the orbital phase" in out[0], out[0][:200])
    expect("a split compound is kept with its hyphen", "two-body system" in out[0] and s["hyphens_kept"] == 60, s)
    last = out[2]
    refs = "".join(last[a:b] for a, b in ranges[2])
    expect("the reference list is marked", "Arenou, F. 2023" in refs and "Halbwachs" in refs, ranges)
    expect("the appendix after the references is not marked", "bit 0 is ra" not in refs and "Appendix A" not in refs, refs)
    expect("nothing on the earlier pages is marked", ranges[0] == [] and ranges[1] == [], ranges)
    arxiv_layout = [body, body, "Conclusions\nDone.\nReferences\nArenou, F., Babusiaux, C., Barstow, M. et al.\n"
                    "2023, A&A, 674, A34\nHalbwachs, J.-L., Pourbaix, D., Arenou, F., et al.\n2023, A&A, 674, A9\n"
                    "Fig. 3: Selection of the astrometric orbital solutions. The first row\n"
                    "refers to a processing trial without the parallax error selection.\n"
                    "Table B.1: cross-match of sources\n6842000081 270.72354 EB 2.10914\n"]
    out3, r3, _ = paper_text.clean(arxiv_layout)
    marked = "".join(out3[2][a:b] for a, b in r3[2])
    expect("a figure caption and a table printed after the references are not marked",
           "Halbwachs" in marked and "Fig. 3" not in marked and "6842000081" not in marked, marked)
    _, r2, s2 = paper_text.clean(["References in the introduction\nsee References\n" + "text " * 200])
    expect("no reference heading in the second half: nothing marked", r2 == [[]] and not s2["references_found"], s2)
    # names of paper notes (ingest_paper.py), from Crossref titles
    expect("italic tags do not glue words: '<i>Gaia</i>Data' -> 'Gaia Data'",
           ingest.plain_title("<i>Gaia</i>Data Release 3: The first<i>Gaia</i>catalogue")
           == "Gaia Data Release 3: The first Gaia catalogue")
    expect("a subscript is followed by a space",
           ingest.plain_title("<i>G</i><sub>RVS</sub>photometry") == "G RVS photometry")
    expect("file names: ': ' -> '. ', '/' -> '-'",
           ingest.sanitize("Gaia DR3: BP/RP spectra", ingest.NOTE_ILLEGAL) == "Gaia DR3. BP-RP spectra")
    expect("a collaboration paper is named by the collaboration and the lead author",
           ingest.prefix(["Gaia Collaboration", "Arenou, F.", "Babusiaux, C."]) == "Gaia Collaboration, Arenou et al"
           and ingest.prefix(["Gosset, E.", "Damerdji, Y.", "Morel, T."]) == "Gosset et al")
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
