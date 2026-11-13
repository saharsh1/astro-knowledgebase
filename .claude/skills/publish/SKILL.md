---
name: publish
description: Share drafts with the group — check every note in outbox/ and move the ones that pass into live/ (the Keeper notes library). Use when the user says "/publish", "share my notes", "publish this lesson", or after /lesson, /digest, /request-paper or /ingest wrote drafts.
---

# /publish

Anything in `live/` reaches every member within minutes, so this is the only way a note
gets there (rule 3). Run from the repository root with the knowledge base's Python.

1. List: `python scripts/publish_notes.py`. Each draft is READY or BLOCKED with reasons.
2. For a BLOCKED draft, fix what you may fix in `outbox/` (frontmatter, tags, place,
   file name) and run step 1 again. Two reasons need the user, never you:
   - a review marker (rule 1): show the user the matching text; only the user decides
     whether to add `markers_reviewed: true`;
   - author is not you: you publish only your own notes. Never change `author`.
3. Show the user the READY list (draft → destination) in a short table and ask once to
   publish them. With a yes: `python scripts/publish_notes.py --apply` (or `--only <files>`
   to publish some).
4. Report what was published and where. Remind that the local search index picks the notes
   up with `cd scripts && HF_HUB_OFFLINE=1 python -m kb_pkg.index`.

Never move or copy files into `live/` by hand, never overwrite a note in `live/`, and never
publish another member's draft.
