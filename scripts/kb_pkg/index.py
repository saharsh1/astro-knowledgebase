"""Incremental builder for the knowledge base's search index.

Indexed sources:
- notes   every .md in live/ (arms and shared folders) and keeper/generated/
          (source_type "note"; "docs" for the Gaia data-model and documentation notes)
- papers  the PDF of every paper note (frontmatter `pdf:`, in keeper/pdfs/), under
          the paper note's name (source_type "paper")
- code    the checkouts in external/ (scripts/fetch_code.py): .py and .jl files by
          function/class, notebooks by cells, README/docs .md by heading
          (source_type "code"; author = repository name)

Labels: every passage carries `arms`, the arms it belongs to ('|a|b|', or '' for code
and documentation). A note: its folder's arm plus its `arms:`. A paper (note and PDF): its
`arms:` plus every arm whose notes link to it. When only the labels of a source change
(e.g. a new note cites a paper), its passages are relabelled without embedding them again.

Usage:
    python -m kb_pkg.index [--rebuild] [--device auto|cpu|mps|cuda]   (from scripts/)
"""
import argparse
import hashlib
import re
from pathlib import Path

import yaml

from . import chunk, config, extract
from .code_chunk import chunk_code_file
from .embed import Embedder
from .store import Store

CODE_SUFFIXES = {".py", ".ipynb", ".jl"}
DOCS_TYPES = {"gaia-table", "gaia-section"}          # note types indexed as source_type "docs"
WIKILINK = re.compile(r"(?<!\!)\[\[([^\]|#]+)")
DOC_SUFFIXES = {".md", ".rst", ".txt"}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frontmatter(p: Path) -> dict:
    t = p.read_text(encoding="utf-8")
    if not t.startswith("---"):
        return {}
    try:
        return yaml.safe_load(t[4:t.find("\n---", 4)]) or {}
    except yaml.YAMLError:
        return {}


def _arms_list(fm: dict) -> list[str]:
    v = fm.get("arms") or []
    return [str(a) for a in (v if isinstance(v, list) else [v])]


def labels(arms) -> str:
    """'|a|b|' for a set of arms, '' for none: the stored form, which LIKE '%|a|%' matches."""
    arms = sorted(a for a in arms if a)
    return "|" + "|".join(arms) + "|" if arms else ""


def discover() -> dict[str, tuple[str, Path, dict]]:
    """source_id -> (kind, path, extra) for every file to index.
    extra['arms'] is the label string and extra['stype'] the source type of a note."""
    found: dict[str, tuple[str, Path, dict]] = {}
    known_arms = set(config.arms())
    notes: list[tuple[Path, dict, str | None]] = []
    for folder in config.note_folders():
        for p in sorted(folder.rglob("*.md")):
            notes.append((p, _frontmatter(p), config.arm_of(p)))

    papers = {p.stem: p for p, fm, _ in notes if fm.get("type") == "paper"}
    cited: dict[str, set[str]] = {s: set() for s in papers}          # paper stem -> arms citing it
    for p, fm, arm in notes:
        if arm:
            for target in WIKILINK.findall(p.read_text(encoding="utf-8", errors="replace")):
                target = target.strip()
                if target in cited:
                    cited[target].add(arm)

    for p, fm, arm in notes:
        rel = p.relative_to(config.ROOT).as_posix()
        arms = {arm, *_arms_list(fm)} if arm else set(_arms_list(fm))
        if fm.get("type") == "paper":
            arms |= cited.get(p.stem, set())
        arms &= known_arms
        stype = "docs" if fm.get("type") in DOCS_TYPES else "note"
        found[rel] = ("note", p, {"arms": labels(arms), "stype": stype})
        if fm.get("type") == "paper":
            pdf = fm.get("pdf") or ""
            if pdf and (config.ROOT / pdf).exists():
                found[p.stem] = ("paper", config.ROOT / pdf, {"arms": labels(arms), "stype": "paper"})
    demos = config.ROOT / "demos"                     # the knowledge base's own notebooks
    for p in sorted(demos.glob("*.ipynb")) if demos.exists() else []:
        rel = p.relative_to(demos).as_posix()
        found[f"code:demos/{rel}"] = ("code", p, {"repo": "demos", "rel": rel})
    for repo in config.repositories():
        base = config.EXTERNAL_DIR / repo["name"]
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or ".git" in p.parts:
                continue
            rel = p.relative_to(base).as_posix()
            if p.suffix in CODE_SUFFIXES:
                found[f"code:{repo['name']}/{rel}"] = ("code", p, {"repo": repo["name"], "rel": rel})
            elif p.suffix in DOC_SUFFIXES and p.stat().st_size < 2_000_000:
                found[f"code:{repo['name']}/{rel}"] = ("codedoc", p, {"repo": repo["name"], "rel": rel})
    return found


def chunks_for(source_id: str, kind: str, path: Path, extra: dict, count=None):
    if kind == "paper":
        return chunk.chunk_paper(source_id, extract.extract_pdf(path), count=count)
    if kind == "code":
        return chunk_code_file(extra["repo"], extra["rel"], path, count=count)
    text = path.read_text(encoding="utf-8", errors="replace")
    if kind == "codedoc":
        out = chunk.chunk_note(source_id, f"{extra['repo']}/{extra['rel']}", text, count=count)
        for c in out:
            c.source_type, c.title, c.author = "code", extra["repo"], extra["repo"]
        return out
    out = chunk.chunk_note(source_id, source_id, text, count=count)
    for c in out:
        c.source_type = extra.get("stype", "note")
    return out


def label_key(extra: dict) -> str:
    return f"{extra.get('stype', '')};{extra.get('arms', '')}"


def build(store, embedder, *, rebuild=False, progress=False) -> dict:
    manifest = {} if rebuild else store.read_manifest()
    if rebuild:
        store.purge(list(store.read_manifest().keys()))
    found = discover()
    counter = getattr(embedder, "token_counter", None)
    count = counter() if callable(counter) else None
    bar = None
    if progress:
        try:
            from tqdm import tqdm
            bar = tqdm(total=len(found), desc="indexing", unit="file")
        except ImportError:
            bar = None
    indexed = skipped = relabelled = total_chunks = 0
    new_manifest: dict[str, str] = {}
    try:
        for source_id, (kind, path, extra) in found.items():
            h, key = file_hash(path), label_key(extra)
            new_manifest[source_id] = f"{h} {key}"
            old_h, _, old_key = manifest.get(source_id, "").partition(" ")
            if old_h == h and old_key == key:
                skipped += 1
            elif old_h == h:                               # same text, new labels: no embedding
                store.relabel(source_id, arms=extra.get("arms", ""),
                              source_type=extra.get("stype") or ("code" if kind in ("code", "codedoc") else kind))
                relabelled += 1
            else:
                chunks = chunks_for(source_id, kind, path, extra, count)
                for c in chunks:
                    c.arms = extra.get("arms", "")
                if chunks:
                    vectors = embedder.embed_passages([c.text for c in chunks])
                    store.upsert(chunks, vectors)
                    indexed += 1
                    total_chunks += len(chunks)
            if bar is not None:
                bar.update(1)
                bar.set_postfix(indexed=indexed, skipped=skipped, chunks=total_chunks)
    finally:
        if bar is not None:
            bar.close()
    deleted = [sid for sid in manifest if sid not in found]
    if deleted:
        store.purge(deleted)
    store.write_manifest(new_manifest)
    return {"indexed": indexed, "relabelled": relabelled, "skipped": skipped,
            "purged": len(deleted), "chunks": total_chunks}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Build or refresh the knowledge base's search index.")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--device", default="auto", help="auto | cpu | mps | cuda | cuda:N")
    a = ap.parse_args(argv)
    stats = build(Store(config.INDEX_DIR), Embedder(device=a.device), rebuild=a.rebuild, progress=True)
    print(" ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
