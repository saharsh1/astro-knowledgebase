#!/usr/bin/env python
"""Tests of the arm and docs labels in the search index.

Builds a small vault (two arms, a shared paper with a one-page PDF, a Gaia data-model note
and a code card), indexes it with a stand-in embedder (no model download), and checks:
- each passage's arms and source type;
- the filters arm= and source_type="docs", alone and together;
- a new note citing the paper adds that arm to the paper by relabelling, with no new embedding.
Needs lancedb and pymupdf (the knowledge base's environment).

    python scripts/test_index_labels.py
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

CHILD = r'''
import hashlib, json, sys
sys.path.insert(0, "scripts")
from kb_pkg import index
from kb_pkg.store import Store
from kb_pkg import config

class FakeEmbedder:
    """8 numbers per text from its hash: the same text gives the same vector."""
    calls = 0
    def _vec(self, text):
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255 for b in h[:8]]
    def embed_passages(self, texts):
        FakeEmbedder.calls += len(texts)
        return [self._vec(t) for t in texts]
    def embed_query(self, q):
        return self._vec(q)

store = Store(config.INDEX_DIR)
emb = FakeEmbedder()
stats = index.build(store, emb)
q = emb.embed_query("anything")
def ids(**kw):
    return sorted({(h["source_id"], h["source_type"], "|".join(h["arms"])) for h in store.search(q, 200, **kw)})
print(json.dumps({"stats": stats, "embedded": FakeEmbedder.calls,
                  "all": ids(), "bs": ids(arm="binary-stars"), "mw": ids(arm="milky-way"),
                  "docs": ids(source_type="docs"), "gaia": ids(arm="gaia"), "bs_paper": ids(arm="binary-stars", source_type="paper"),
                  "either": ids(arm=["milky-way", "hot-stars"])}))
'''

FAILS: list[str] = []


def expect(name: str, ok: bool, detail="") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        print("     " + str(detail))


def write(path: Path, fm: str, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm.strip()}\n---\n{body}\n", encoding="utf-8")


def run(root: Path) -> dict:
    import json
    r = subprocess.run([sys.executable, "-c", CHILD], cwd=root, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


def main() -> int:
    import pymupdf
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / "vault"
        (root / "scripts").mkdir(parents=True)
        shutil.copytree(REPO / "scripts" / "kb_pkg", root / "scripts" / "kb_pkg")
        shutil.copy(REPO / "conventions.yaml", root)
        (root / "sources.yaml").write_text("repositories: []\n")
        live, keeper = root / "live", root / "keeper"

        write(live / "binary-stars/notes/BS note.md", "title: BS note\ntype: note\nauthor: a\ncreated: x\ntags: []",
              "Orbits of binaries. See [[Paper A]].")
        write(live / "milky-way/notes/MW note.md", "title: MW note\ntype: note\nauthor: a\ncreated: x\n"
              "arms: [hot-stars]\ntags: []", "Disc kinematics.")
        pdf = keeper / "pdfs" / "Paper A.pdf"
        pdf.parent.mkdir(parents=True)
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "A paper about a black hole in a binary.")
        doc.save(pdf)
        write(live / "papers/Paper A.md", "title: Paper A\ntype: paper\nauthor: a\ncreated: x\ntags: []\n"
              "arms: [binary-stars]\narxiv: '1'\nbibtex: b\npdf: keeper/pdfs/Paper A.pdf", "Abstract.")
        write(live / "gaia/lessons/2026-11-13 - c - Period.md",
              "title: Period\ntype: lesson\nkind: tip\nauthor: c\ncreated: x\nlast_checked: x\nstatus: current\n"
              "applies_to: ['dr3:nss_two_body_orbit.period']\ntags: [NSS]", "The period is in days.")
        write(live / "code/orblet.md", "title: orblet\ntype: code-card\nauthor: a\ncreated: x\ntags: []\n"
              "repo: orblet\nverified_at: abc", "A fitting code.")
        write(keeper / "generated/gaia-docs/DR4 draft - nss_two_body_orbit.md",
              "title: t\ntype: gaia-table\nauthor: g\ncreated: x\ntags: []\nrelease: DR4\ndoc_version: d\ngenerated: true",
              "period: orbital period in days.")

        r1 = run(root)
        all1 = {s: (st, arms) for s, st, arms in r1["all"]}
        expect("every source is indexed", len(all1) == 7, r1["all"])
        expect("an arm note carries its arm", all1.get("live/binary-stars/notes/BS note.md") == ("note", "binary-stars"),
               all1)
        expect("a note's arms: field adds arms", all1.get("live/milky-way/notes/MW note.md") == ("note", "hot-stars|milky-way"),
               all1)
        expect("the paper PDF carries the paper note's arms", all1.get("Paper A") == ("paper", "binary-stars"), all1)
        expect("a data-model note is source_type docs, in the gaia arm",
               all1.get("keeper/generated/gaia-docs/DR4 draft - nss_two_body_orbit.md") == ("docs", "gaia"), all1)
        expect("a code card has no arm", all1.get("live/code/orblet.md") == ("note", ""), all1)
        bs = {s for s, _, _ in r1["bs"]}
        expect("arm=binary-stars: its note and its paper, nothing else",
               bs == {"live/binary-stars/notes/BS note.md", "live/papers/Paper A.md", "Paper A"}, bs)
        expect("source_type=docs: only the documentation",
               {s for s, _, _ in r1["docs"]} == {"keeper/generated/gaia-docs/DR4 draft - nss_two_body_orbit.md"}, r1["docs"])
        expect("arm=gaia: the documentation and the gaia lesson",
               {s for s, _, _ in r1["gaia"]} == {"keeper/generated/gaia-docs/DR4 draft - nss_two_body_orbit.md",
                                                  "live/gaia/lessons/2026-11-13 - c - Period.md"}, r1["gaia"])
        expect("arm and source_type combine", {s for s, _, _ in r1["bs_paper"]} == {"Paper A"}, r1["bs_paper"])
        expect("a list of arms means any of them", {s for s, _, _ in r1["either"]} == {"live/milky-way/notes/MW note.md"},
               r1["either"])

        write(live / "binary-stars/notes/BS uses period.md",
              "title: BS uses period\ntype: note\nauthor: a\ncreated: x\ntags: []",
              "Uses [[DR4 draft - nss_two_body_orbit#period|the period]].")
        write(live / "milky-way/notes/MW cites A.md", "title: MW cites A\ntype: note\nauthor: a\ncreated: x\ntags: []",
              "The disc population in [[Paper A]].")
        r2 = run(root)
        mw = {s for s, _, _ in r2["mw"]}
        expect("a milky-way note citing the paper adds milky-way to the paper",
               {"Paper A", "live/papers/Paper A.md"} <= mw, r2["mw"])
        expect("the paper was relabelled, not embedded again",
               r2["stats"]["relabelled"] == 2 and r2["stats"]["indexed"] == 2, r2["stats"])
        u = subprocess.run([sys.executable, "-c", "import json,sys; sys.path.insert(0,'scripts');"
                            "from kb_pkg.usage import notes_using_column as f;"
                            "print(json.dumps(f('nss_two_body_orbit','period')))"],
                           cwd=root, capture_output=True, text=True)
        import json
        used = {(d["note"], d["arm"], tuple(d["how"])) for d in json.loads(u.stdout or "[]")}
        expect("notes_using_column: the gaia lesson (applies_to) and the binary note (link)",
               used == {("[[2026-11-13 - c - Period]]", "gaia", ("applies_to",)),
                        ("[[BS uses period]]", "binary-stars", ("link",))}, u.stdout + u.stderr)
        r3 = run(root)
        expect("a third run with no change does nothing",
               r3["stats"]["indexed"] == 0 and r3["stats"]["relabelled"] == 0 and r3["embedded"] == 0, r3["stats"])

    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
