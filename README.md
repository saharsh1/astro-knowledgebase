# Astro knowledge base

The group's shared knowledge base: notes, papers, Gaia documentation, code cards and
lessons, organised in topical **arms** (binary stars, Milky Way, hot stars, …), read in
Obsidian and searched with Claude.

This repository is the **skeleton**: rules (`CLAUDE.md`), conventions, templates,
scripts and skills. The notes and data are not here. They live in two Keeper libraries,
which the Seafile app syncs into `live/` (notes) and `keeper/` (data).

**Status (2026-11-13): under construction.**

- Done: rules, conventions, templates, checker, hooks; the skills `/publish`,
  `/request-paper`, `/ingest`, `/lesson`, `/digest` and their scripts; arm and docs
  labels in the search index, with `arm=` and `source_type="docs"` filters.
- To come: `/consolidate`, `/resolve`, `/sync`, `/share`, `/publish-index`; `setup.sh`
  and `doctor.py`; the snapshot script; the import of the binary stars knowledge base.

The design is in `docs/design/`.

Check the skeleton and run the tests:

```bash
python scripts/check_vault.py
python scripts/test_check_vault.py
python scripts/test_notes_flow.py
python scripts/test_index_labels.py   # needs the full environment (lancedb, pymupdf)
```
