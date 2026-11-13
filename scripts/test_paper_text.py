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
    # author and affiliation lists
    front = ("Gaia scan-angle-dependent signals and spurious periods\nB. Holl\n1, 2,**, C. Fabricius\n3, 4, J. Portell\n"
             "4, 3, L. Lindegren\n5, P. Panuzzo\n6, M. Bernet\n4, 3, J. Castañeda\n4, 3,\n"
             "Jean-Louis Halbwachs1, Dimitri Pourbaix*2, Frédéric Arenou3\n"
             "1 Université de Strasbourg, CNRS, Observatoire astronomique de Strasbourg\n"
             "2 FNRS, Institut d’Astronomie et d’Astrophysique, Université Libre de Bruxelles\n"
             "ABSTRACT\nContext. Gaia EDR3 and Gaia DR2 differ. We thank C. Fabricius for comments.\n"
             "11 https://gea.esac.esa.int/archive/documentation/GDR3/\n"
             "5p (astrometric_params_solved = 31)\n6p (astrometric_params_solved = 95)\n")
    out4, _, s4 = paper_text.clean([front])
    marked = "".join(out4[0][a:b] for a, b in s4["authors"][0])
    expect("author lists are marked: initials with numbers on the next line, full names, affiliations",
           "C. Fabricius" in marked and "Dimitri Pourbaix" in marked and "Université de Strasbourg" in marked, marked)
    expect("the title, the abstract, a sentence naming one person, URLs and parameter lines are not marked",
           not any(x in marked for x in ("spurious periods", "ABSTRACT", "We thank", "https", "5p (")), marked)

    affils = ("Results of the paper end here and are long enough to stand alone as a sentence.\n"
              "26 Royal Observatory of Belgium, Ringlaan 3, 1180 Brussels, Belgium\n"
              "27 Observational Astrophysics, Division of Astronomy and Space\n"
              "Physics, Department of Physics and Astronomy, Uppsala University, Box 516, 751 20 Uppsala,\n"
              "28 ALTEC S.p.a, Corso Marche, 79,10146 Torino, Italy\n"
              "29 Sàrl, Geneva, Switzerland\n"
              "30 Department of Astronomy, University of Geneva, Chemin d’Ecogia\n"
              "16, 1290 Versoix, Switzerland\n"
              "Avanzati, via Bonomea 265, 34136 Trieste, Italy 81 Telespazio for CNES Centre Spatial\n"
              "31 Mullard Space Science Laboratory, University College London,\n")
    out5, _, s5 = paper_text.clean([affils])
    marked = "".join(out5[0][a:b] for a, b in s5["authors"][0])
    expect("an affiliation list with address lines and mid-line numbers is marked through",
           all(x in marked for x in ("Royal Observatory", "ALTEC", "Versoix", "Telespazio", "Mullard"))
           and "Results of the paper" not in marked, marked)

    # names of paper notes (ingest_paper.py), from Crossref titles
    expect("italic tags do not glue words: '<i>Gaia</i>Data' -> 'Gaia Data'",
           ingest.plain_title("<i>Gaia</i>Data Release 3: The first<i>Gaia</i>catalogue")
           == "Gaia Data Release 3: The first Gaia catalogue")
    expect("a tag next to punctuation adds no space: '(Gaia-CRF3)', 'Gaia’s'",
           ingest.plain_title("The celestial reference frame (<i>Gaia</i>-CRF3) and <i>Gaia</i>’s PSF")
           == "The celestial reference frame (Gaia-CRF3) and Gaia’s PSF")
    expect("a line break after a tag (Crossref) adds no space before '-'",
           ingest.plain_title("(<i>Gaia</i>\n                    -CRF3)") == "(Gaia-CRF3)"
           and ingest.plain_title("<i>Gaia</i>\n                    Early Data Release 3") == "Gaia Early Data Release 3")
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
