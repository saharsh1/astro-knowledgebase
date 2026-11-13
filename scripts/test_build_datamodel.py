#!/usr/bin/env python
"""Tests of scripts/build/gaia_datamodel.py and the data-model parser.

1. Fetch and locks, on a throwaway vault with a small synthetic data-model PDF: a file
   whose SHA-256 differs from sources.yaml is refused; the right one is stored with locks;
   a rebuild reuses it; a stored file changed afterwards is refused.
2. Regression on the real DR4 draft (2026-06-26), if this machine has it in
   keeper/data/gaia/DR4-draft/: tables, columns, units, and the 28 columns whose text
   holds a table or formula, each checked by eye on the page on 2026-11-13.
Needs pymupdf (the knowledge base's environment).

    python scripts/test_build_datamodel.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILS: list[str] = []

FLAGGED_DR4_DRAFT = {
    "all_source_astrometry.astrometric_params", "all_source_astrometry.which_matched_semesters",
    "all_source_match.rule", "ap_class.flags_oa", "ap_class.flags_uca", "ap_rvs.flags_gspspec",
    "ap_rvs.flags_gspspec_ann", "ap_rvs_epoch.flags_gspspec", "bright_source_astrometry.astrometric_params",
    "crowded_field_source.astrometric_params", "gaia_source.astrometric_params",
    "gaia_source.rv_expected_sig_to_noise", "grav_lens_combination.flag", "grav_lens_observation.bp_flag",
    "grav_lens_observation.rp_flag", "grav_lens_xp_mean_spectrum.bp_flags", "grav_lens_xp_mean_spectrum.rp_flags",
    "nss_acceleration_astro.flags", "nss_multiple_orbits.bit_index", "nss_multiple_orbits.flags",
    "nss_non_linear_spectro.bit_index", "nss_non_linear_spectro.flags",
    "nss_resolved_pair.curvature_relative_motion", "nss_two_body_orbit.bit_index", "nss_two_body_orbit.flags",
    "nss_vim_fl.flags", "rvs_epoch_parameters_single.outlier_status", "vari_eclipsing_binary.num_model_parameters",
}


def expect(name: str, ok: bool, detail="") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        print("     " + str(detail).strip().replace("\n", "\n     "))


def synthetic_zip(path: Path) -> None:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 150), "orbits", fontsize=14.3)
    page.insert_text((72, 180), "A table of orbits.", fontsize=10)
    page.insert_text((72, 210), "Columns description:", fontsize=10)
    page.insert_text((72, 240), "period : Orbital period (double, Time[d])", fontsize=14.3)
    page.insert_text((72, 260), "The orbital period of the binary.", fontsize=10)
    doc.set_toc([[1, "Binaries", 1], [2, "orbits", 1]])
    pdf = path.with_name("model.pdf")
    doc.save(pdf)
    with zipfile.ZipFile(path, "w") as z:
        z.write(pdf, "model.pdf")
        z.writestr("readme.txt", "synthetic")


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        root = tmp / "vault"
        (root / "scripts").mkdir(parents=True)
        shutil.copy(REPO / "scripts/kb_common.py", root / "scripts")
        shutil.copytree(REPO / "scripts/build", root / "scripts/build")
        shutil.copy(REPO / "conventions.yaml", root)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "github.user", "keeper1"], check=True)
        good = tmp / "dm.zip"
        synthetic_zip(good)
        sha = hashlib.sha256(good.read_bytes()).hexdigest()
        (root / "sources.yaml").write_text(
            "repositories: []\ngaia:\n  - label: T-draft\n    release: DR4\n    status: draft\n"
            "    doc_version: draft 1\n    page: https://example.org/gaia\n    replaced_by: the formal one\n"
            f"    datamodel:\n      zip: https://example.org/dm.zip\n      sha256: {sha}\n      pdf: model.pdf\n")
        bad = tmp / "other.zip"
        bad.write_bytes(good.read_bytes() + b"x")

        def build(*args) -> tuple[int, str]:
            r = subprocess.run([sys.executable, str(root / "scripts/build/gaia_datamodel.py"), "T-draft", *args],
                               cwd=root, capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr

        code, out = build("--from", str(bad))
        expect("a file that is not the published one is refused",
               code != 0 and "not the published file" in out and not (root / "keeper/data/gaia/T-draft/dm.zip").exists(), out)
        code, out = build("--from", str(good))
        k = root / "keeper"
        col = json.loads((k / "parsed/gaia/T-draft/columns.jsonl").read_text().splitlines()[0]) \
            if (k / "parsed/gaia/T-draft/columns.jsonl").exists() else {}
        expect("the published file is stored, locked, parsed and turned into notes",
               code == 0 and (k / "locks/data/gaia/T-draft/dm.zip.json").exists()
               and (k / "locks/data/gaia/T-draft/model.pdf.json").exists()
               and col.get("unit") == "d" and col.get("status") == "draft"
               and (k / "generated/gaia/T-draft/datamodel/T-draft - orbits.md").exists(), out + str(col))
        note = (k / "generated/gaia/T-draft/datamodel/T-draft - orbits.md").read_text() if code == 0 else ""
        expect("the note says it is a draft and what replaces it",
               "release_status: draft" in note and "[!warning] Draft" in note and "the formal one" in note, note[:800])
        code, out = build()
        expect("a rebuild reuses the stored file (no download)", code == 0 and "downloading" not in out, out)
        (k / "data/gaia/T-draft/model.pdf").write_bytes(b"%PDF changed")
        code, out = build()
        expect("a stored file changed after its lock is refused", code != 0 and "differs from its lock" in out, out)

    real = REPO / "keeper/parsed/gaia/DR4-draft"
    if not (REPO / "keeper/data/gaia/DR4-draft").exists():
        print("SKIP the DR4 draft regression: keeper/data/gaia/DR4-draft/ is not on this machine")
    else:
        sys.path.insert(0, str(REPO / "scripts/build"))
        import datamodel_pdf
        pdf = REPO / "keeper/data/gaia/DR4-draft/gaia-dr4-prerelease-draft-data-model.pdf"
        tables, cols, rep = datamodel_pdf.parse(pdf, release="DR4", doc_version="draft 2026-06-26",
                                                label="DR4-draft", status="draft")
        expect("DR4 draft: 141 of 141 tables, 4,629 columns, no duplicates, 2 headers without a type",
               (rep["tables_found"], rep["outline_tables"], rep["columns"], len(rep["duplicate_columns"]),
                len(rep["unparsed_headers"])) == (141, 141, 4629, 0, 2), {k: rep[k] for k in ("tables_found", "columns")})
        by = {f"{c['table']}.{c['column']}": c for c in cols}
        p = by["nss_two_body_orbit.period"]
        expect("DR4 draft: nss_two_body_orbit.period is a double in days",
               (p["datatype"], p["quantity"], p["unit"]) == ("double", "Time", "day"), p)
        flagged = {k for k, c in by.items() if c["has_embedded_table"]}
        expect("DR4 draft: the 28 columns holding a table or formula, no more, no fewer",
               flagged == FLAGGED_DR4_DRAFT, {"missing": sorted(FLAGGED_DR4_DRAFT - flagged),
                                              "extra": sorted(flagged - FLAGGED_DR4_DRAFT)})
        expect("DR4 draft: the bit_index tables of nss_two_body_orbit are on pp. 814, 816, 817, 820",
               by["nss_two_body_orbit.bit_index"]["embedded_table_pages"] == [814, 816, 817, 820],
               by["nss_two_body_orbit.bit_index"]["embedded_table_pages"])
        if real.exists():
            stored = sum(1 for _ in open(real / "columns.jsonl"))
            expect("the stored parse in keeper/ matches a fresh one", stored == len(cols), stored)

    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
