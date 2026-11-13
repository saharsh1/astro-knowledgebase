---
name: sync
description: Bring this clone of the astro knowledge base up to date — pull the skeleton from GitHub, check the two Keeper libraries (keeper/, live/), conflict copies and outbox drafts, put the code checkouts at their pins, copy a newer published search index and index what is newer here. Use at the start of a session, when the session-start note says the clone is behind, or when the user says "/sync" or "update the knowledge base".
---

# /sync

Run from the repository root with the knowledge base's Python (the `bskb` environment).

1. `python scripts/sync.py`. It prints one line per step: OK, DONE (updated now), WARN
   (works, something is behind) or STOP (needs the user). Indexing new notes or papers
   loads the search model; with many new sources it can take minutes, so run it in the
   background and wait for it. `--no-build` only reports what the index lacks; `--offline`
   skips GitHub; `--full` also compares the checksums of every Keeper file.
2. Act on the lines, in this order:
   - **STOP skeleton, tracked files changed:** ask the user whether to `/share` them or
     `git stash` them. Never discard them. Then run step 1 again.
   - **STOP skeleton, another branch or local commits on main:** tell the user; offer
     `git switch main` when their branch is already shared. Never reset or delete commits.
   - **STOP keeper/ or live/ missing:** the user syncs that Keeper library with the Seafile
     app ("sync with an existing folder"). You cannot do it.
   - **WARN keeper/, files missing or different:** usually Seafile is still downloading.
     Say so; do not touch `keeper/`.
   - **WARN live/, conflict copies:** offer `/resolve`.
   - **WARN outbox/:** offer `/publish` for the drafts that are ready.
   - **DONE skeleton with a new rules version:** read `CLAUDE.md` and `conventions.yaml`
     again before writing anything.
   - **WARN Python environment:** give the user `conda env update -n bskb -f environment.yml`.
3. Report in a few lines: what was updated, what is still behind, what the user must do.

Never push, never edit `external/`, `index/` or anything in `keeper/`, and never move,
delete or rename files in `live/` (conflict copies go through `/resolve`).
