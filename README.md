# Astro knowledge base

The group's shared knowledge base: notes, papers, Gaia documentation, code cards and
lessons, organised in **arms** in three layers: `gaia` (documentation, data model,
verification papers), `software` (the group's code and its documentation), and the science
arms (binary stars, Milky Way, hot stars, …).
Read in Obsidian and searched with Claude.

This public repository is the **skeleton**: rules (`CLAUDE.md`), conventions, templates,
scripts and skills. The notes and data are not here. They live in two closed Keeper
libraries, which the Seafile app syncs into `live/` (notes) and `keeper/` (data). Without
access to them, the skeleton still runs its checks and tests.

**Status (2026-11-13): under construction.**

- Done: rules, conventions, templates, checker, hooks; the skills `/publish`,
  `/request-paper`, `/ingest`, `/lesson`, `/digest`, `/consolidate`, `/resolve` and their
  scripts; arm and docs labels in the search index, with `arm=` and `source_type="docs"`;
  the layered arms gaia / software / science (links run down the layers; notes in
  `lookup_column`); the public guard (`check_public.py`) and the licences.
- Next: `scripts/build/`: the Gaia documentation and data model (DR3 now, DR4 from its
  release on 2 December 2026), the verification papers from ESA's papers pages (with PDF
  text cleaning), the code documentation; then a fresh index. Nothing is imported from the
  old binary stars knowledge base.
- To come: `/sync`, `/share`, `/publish-index`; `setup.sh` and `doctor.py`; the snapshot
  script.

The design is in `docs/design/`.

Check the skeleton and run the tests:

```bash
python scripts/check_vault.py
python scripts/check_public.py
python scripts/test_check_public.py
python scripts/test_check_vault.py
python scripts/test_notes_flow.py
python scripts/test_consolidate_resolve.py
python scripts/test_index_labels.py   # needs the full environment (lancedb, pymupdf)
```

Licences: MIT for the code (`LICENSE`), CC BY 4.0 for the text (`LICENSE-docs.md`).
