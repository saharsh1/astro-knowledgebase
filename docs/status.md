# Status and build log

For people who maintain the knowledge base. Members do not need this page; start at the
[README](../README.md).

**Status (2026-11-15):** built, and running against GitHub and Keeper; beta testing with the
first members. The published search index is version 2026-11-13.4 (21,007 passages).

## What was built, in order

- Done: rules, conventions, templates, checker, hooks; the skills `/publish`,
  `/request-paper`, `/ingest`, `/lesson`, `/digest`, `/consolidate`, `/resolve` and their
  scripts; arm and docs labels in the search index, with `arm=` and `source_type="docs"`;
  the layered arms gaia / software / science (links run down the layers; notes in
  `lookup_column`); the public guard (`check_public.py`) and the licences.
- Built: the DR4 **draft** data model (2026-06-26), `scripts/build/gaia_datamodel.py DR4-draft`:
  141 tables, 4,629 columns, labelled `DR4-draft` everywhere; replaced by the formal DR4
  data model at the release (planned 2 December 2026).
- Built: the DR3 documentation 1.3, `scripts/build/gaia_docs.py DR3`: a snapshot of the
  646 web pages; 94 data-model tables, 2,093 columns, checked against the archive's own
  column list; 552 section notes with links between pages and to columns.
- Built: the papers on ESA's DR3 and EDR3 papers pages (57), `scripts/build/gaia_papers.py DR3|EDR3`
  (arm `gaia`; metadata from Crossref and arXiv, no token needed; PDFs from arXiv), and
  their cleaned text, `scripts/build/paper_text.py` (ligatures, split words, reference lists).
- Built: the `software` arm's generated part: the five pinned repositories checked out
  (`scripts/fetch_code.py`), the Gaia columns their code reads (`scripts/build/code_usage.py`),
  and one summary note per repository (`scripts/build/software_docs.py`).
- Built: the first index of all of it (local `index/`, 2026-11-13): 21,215 passages from
  1,086 sources, 56 min on Apple MPS: Gaia documentation 12,698, papers 5,038, code 3,181,
  notes 298. BibTeX notes are not indexed.
- The paper text leaves out reference lists and author and affiliation lists (Gaia
  Collaboration papers list hundreds of authors, which ranked high in search).
- Built: `/publish-index` (`scripts/publish_index.py`): the index keeper publishes the index
  to `keeper/index/` with a version, an archive of 3 earlier versions and a history line in
  Keeper (not in git: it names private notes); members `--pull` it. `scripts/regenerate.sh`
  rebuilds the software arm's notes after the code pins move.
- Next: the DR4 papers and documentation at the release. Nothing is imported from the
  old binary stars knowledge base.
- Built: `/sync` (`scripts/sync.py`): pulls the skeleton (fast-forward only, never over local
  changes), checks both Keeper libraries, conflict copies and drafts, puts the code at its pins,
  copies a newer published index and indexes what is newer here. About 5 s when nothing changed.
- Built: `/share` (`scripts/share.py`): a change to the skeleton becomes a branch
  `<user>/<date>-<topic>` and a pull request, committed only after the public-repository guard,
  the checker and the GitHub check's tests pass; pushed only after the user's yes.
- Built: `scripts/setup.sh` (environment, `config.local`, GitHub name, pre-commit check, the
  pinned search model, then the `/sync` steps and the doctor) and `scripts/doctor.py` (16 checks
  of setup, content and a working search server; changes nothing; `--fast` skips the model).
- Measured: `scripts/eval_search.py` runs the questions of `scripts/eval_questions.yaml` (30, each
  with its right sources). 2026-11-13: right source first for 20, in the top 5 for 28, in the top 10
  for all 30; 7.6 different sources per top 10. A result list holds at most 2 passages of one
  source (`per_source`); the documentation's bibliography is not indexed.
- Each paper passage starts with its paper's title and section (found from the numbered headings),
  so a hit says where it is from. The headings are told by their font when the paper text is
  cleaned (`paper_text.py`): 1,922 headings in the 56 papers, numbered lists excluded. Measured on
  the 30 questions: first 19, top 3 26, top 5 29, top 10 30.
- Built: `scripts/snapshot_notes.py` (owner): a dated zip of all notes in `keeper/snapshots/` and a
  report of what changed since the one before (new, changed, deleted, author changed, conflict
  copies, review markers); `--restore` writes into `outbox/`. Each index version names the newest
  snapshot. First snapshot: `notes-2026-11-13`.
- Built: `scripts/build/home.py` (index keeper, at `/publish-index`): the entry pages in
  `keeper/generated/`: Home, `Index - papers`, `Index - lessons` and one `Arm - <name>` page per
  arm. `--bookmarks` (run by `setup.sh`) bookmarks them in Obsidian on each machine. Not in the
  search index.

## Tests

The first ten run on every pull request (`.github/workflows/check.yml`). The others need
the full Python environment, and some need the Keeper data.

```bash
python scripts/check_vault.py
python scripts/check_public.py
python scripts/test_check_public.py
python scripts/test_check_vault.py
python scripts/test_notes_flow.py
python scripts/test_consolidate_resolve.py
python scripts/test_paper_text.py
python scripts/test_snapshot_notes.py
python scripts/test_build_software.py
python scripts/test_build_home.py
python scripts/test_index_labels.py     # needs the full environment (lancedb, pymupdf)
python scripts/test_publish_index.py   # needs lancedb
python scripts/test_sync.py            # needs lancedb
python scripts/test_paper_sections.py  # needs pymupdf
python scripts/test_share.py           # runs the GitHub check's tests in a copy (not in CI itself)
python scripts/test_setup_doctor.py    # needs the full environment and the model in the cache
python scripts/test_build_datamodel.py  # needs pymupdf; checks the DR4 draft if keeper/ has it
python scripts/test_build_docs.py --real # needs beautifulsoup4; checks the DR3 build if keeper/ has it
```

The design and the reasons behind it are in [design/](design/).
