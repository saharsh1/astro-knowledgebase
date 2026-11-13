#!/usr/bin/env python
"""Offline tests of the note flow: request a paper, publish drafts, ingest roles, locks.

Builds a throwaway vault (the skeleton plus live/ and keeper/), runs the scripts as a member
(bob) and as a curator (alice), and fails if a step does not behave as the rules say.
No network: SciX and the PDF download are not called.

    python scripts/test_notes_flow.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
FAILS: list[str] = []
SCRIPTS = ["check_vault.py", "kb_common.py", "publish_notes.py", "request_paper.py", "ingest_paper.py"]


def expect(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)
        if detail:
            print("     " + detail.strip().replace("\n", "\n     "))


def vault(tmp: Path) -> Path:
    root = tmp / "vault"
    (root / "scripts").mkdir(parents=True)
    for s in SCRIPTS:
        shutil.copy(REPO / "scripts" / s, root / "scripts" / s)
    shutil.copytree(REPO / "templates", root / "templates")
    conv = yaml.safe_load((REPO / "conventions.yaml").read_text())
    conv["owner"], conv["curators"] = "alice", ["alice"]
    (root / "conventions.yaml").write_text(yaml.safe_dump(conv, sort_keys=False))
    for arm in conv["arms"]:
        (root / "live" / arm / "notes").mkdir(parents=True)
    (root / "keeper" / "pdfs").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def as_user(root: Path, user: str) -> None:
    subprocess.run(["git", "-C", str(root), "config", "github.user", user], check=True)


def run(root: Path, script: str, *args: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(root / "scripts" / script), *args],
                       capture_output=True, text=True, cwd=root)
    return r.returncode, r.stdout + r.stderr


def write(path: Path, fm: str, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm.strip()}\n---\n{body}\n", encoding="utf-8")


def main() -> int:
    sys.path.insert(0, str(REPO / "scripts"))
    from kb_common import normalize_id
    cases = {"2302.07880": ("arxiv", "2302.07880"), "arXiv:2302.07880v2": ("arxiv", "2302.07880"),
             "https://arxiv.org/abs/2302.07880": ("arxiv", "2302.07880"),
             "10.1093/mnras/stad799": ("doi", "10.1093/mnras/stad799"),
             "https://doi.org/10.1093/mnras/stad799": ("doi", "10.1093/mnras/stad799"),
             "2023MNRAS.521.4323E": ("bibcode", "2023MNRAS.521.4323E"),
             "https://scixplorer.org/abs/2023MNRAS.521.4323E/abstract": ("bibcode", "2023MNRAS.521.4323E")}
    expect("identifiers: arXiv, DOI, bibcode and URLs", all(normalize_id(k) == v for k, v in cases.items()),
           str({k: normalize_id(k) for k in cases}))

    with tempfile.TemporaryDirectory() as t:
        root = vault(Path(t))
        live, outbox = root / "live", root / "outbox"

        # --- a member requests a paper ---------------------------------------------------
        as_user(root, "bob")
        code, out = run(root, "request_paper.py", "2302.07880", "--arm", "binary-stars", "--reason", "Gaia BH2")
        req = next((outbox / "requests").glob("*.md"), None)
        expect("request: written to outbox/requests/", code == 0 and req is not None
               and req.name.endswith(" - bob - 2302.07880.md"), out)
        code, out = run(root, "publish_notes.py", "--apply", "--only", str(req.relative_to(root)))
        expect("request: published to live/requests/", code == 0 and (live / "requests" / req.name).exists(), out)
        code, out = run(root, "request_paper.py", "arXiv:2302.07880v1", "--arm", "milky-way", "--reason", "x")
        expect("request: a second request for the same paper is refused", "already requested by bob" in out, out)
        code, out = run(root, "request_paper.py", "--list")
        expect("request: listed as open", "open" in out and "2302.07880" in out, out)

        # --- the member cannot ingest; the curator sees the request -------------------------
        code, out = run(root, "ingest_paper.py", "2302.07880", "--arm", "binary-stars")
        expect("ingest: refused for a member", code != 0 and "not a curator" in out, out)
        as_user(root, "alice")
        code, out = run(root, "ingest_paper.py", "--list-requests")
        expect("ingest: the curator sees the open request", "1 open request" in out and "by bob" in out, out)

        # what ingest_paper.py writes after SciX: a paper note with the arXiv id
        write(live / "papers" / "El-Badry et al (2023) - A red giant orbiting a black hole.md",
              "title: El-Badry et al (2023) - A red giant orbiting a black hole\ntype: paper\nauthor: alice\n"
              "created: 2026-11-13\ntags: []\narms: [binary-stars]\nbibcode: 2023MNRAS.521.4323E\n"
              "arxiv: '2302.07880'\nbibtex: x\nrequested_by: bob")
        code, out = run(root, "request_paper.py", "--list")
        expect("request: done once a paper note has its id", out.startswith("done"), out)
        as_user(root, "bob")
        code, out = run(root, "request_paper.py", "10.1093/x", "--arm", "binary-stars", "--reason", "x")
        code, out2 = run(root, "request_paper.py", "2023MNRAS.521.4323E", "--arm", "binary-stars", "--reason", "x")
        expect("request: refused when the paper is already in the knowledge base",
               "already in the knowledge base" in out2, out2)
        for p in (outbox / "requests").glob("*.md"):
            p.unlink()

        # --- publish: what is blocked ---------------------------------------------------------
        lesson_fm = ("title: Period unit\ntype: lesson\nkind: tip\nauthor: bob\ncreated: 2026-11-13\n"
                     "last_checked: 2026-11-13\nstatus: current\napplies_to: []\ntags: []")
        good = outbox / "binary-stars/lessons/2026-11-13 - bob - Period unit.md"
        write(good, lesson_fm, "Period is in days.")
        theirs = outbox / "binary-stars/lessons/2026-11-13 - carol - Other.md"
        write(theirs, lesson_fm.replace("author: bob", "author: carol").replace("Period unit", "Other"))
        marked = outbox / "binary-stars/notes/Marked.md"
        write(marked, "title: Marked\ntype: note\nauthor: bob\ncreated: 2026-11-13\ntags: []", "From a DPAC internal note.")
        digest = outbox / "milky-way/notes/Digest - extinction - bob - 2026-11-13.md"
        write(digest, "title: Digest\ntype: note\nauthor: bob\ncreated: 2026-11-13\ntags: []", "No callout.")
        clash = outbox / "papers/El-Badry et al (2023) - A red giant orbiting a black hole.md"
        write(clash, "title: x\ntype: paper\nauthor: bob\ncreated: 2026-11-13\ntags: []\narms: [binary-stars]\n"
                     "arxiv: '1'\nbibtex: x")
        code, out = run(root, "publish_notes.py")
        blocks = out.split("BLOCKED")
        expect("publish: dry run moves nothing", good.exists() and "Nothing moved" in out, out)
        expect("publish: another member's draft is blocked", any("carol" in b and "not you" in b for b in blocks), out)
        expect("publish: a review marker is blocked", any("Marked" in b and "markers_reviewed" in b for b in blocks), out)
        expect("publish: a digest without the AI callout is blocked", any("Digest" in b and "callout" in b for b in blocks), out)
        expect("publish: an existing note is never overwritten", any("El-Badry" in b and "exists already" in b for b in blocks), out)
        code, out = run(root, "publish_notes.py", "--apply")
        expect("publish --apply: only the good draft moves",
               (live / "binary-stars/lessons" / good.name).exists() and not good.exists()
               and theirs.exists() and marked.exists() and digest.exists() and clash.exists(), out)

        # --- locks ---------------------------------------------------------------------------
        sys.path.insert(0, str(root / "scripts"))
        pdf = root / "keeper/pdfs/A paper.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        r = subprocess.run([sys.executable, "-c",
                            "import sys; sys.path.insert(0,'scripts'); from kb_common import write_lock, KEEPER;"
                            "write_lock(KEEPER/'pdfs'/'A paper.pdf','alice','test')"],
                           cwd=root, capture_output=True, text=True)
        code, out = run(root, "check_vault.py", "--keeper")
        expect("lock: written, and the file matches it", r.returncode == 0 and "differs" not in out
               and "no lock" not in out, r.stderr + out)
        pdf.write_bytes(b"%PDF-1.4 changed")
        code, out = run(root, "check_vault.py", "--keeper")
        expect("lock: a changed file is caught", code == 1 and "differs from its lock" in out, out)
        (root / "keeper/pdfs/Unlocked.pdf").write_bytes(b"%PDF")
        code, out = run(root, "check_vault.py", "--keeper")
        expect("lock: a file added without /ingest is reported", "no lock" in out, out)

    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
