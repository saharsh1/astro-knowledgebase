---
name: publish-index
description: Index keeper only — regenerate the software arm's generated notes, update the shared search index from the published one, and publish it to Keeper (keeper/index/) with a history line. Use when the user says "/publish-index", "publish the index", "roll back the index to <version>", or asks which index version is published.
---

# /publish-index

For the index keeper: the owner, or a member listed under `index_keepers:` in
`keeper/roles.yaml`. Members do not need this: their own
`cd scripts && HF_HUB_OFFLINE=1 python -m kb_pkg.index` indexes what is new, and
`python scripts/publish_index.py --pull` copies a newer published index.

Run from the repository root with the knowledge base's Python (the `bskb` environment).

1. **Status.** `python scripts/publish_index.py --status`: the published version, the local
   one, the archive and the last history lines. Stop if a LOCK younger than 4 h is shown.
2. **Skeleton up to date.** The clone must be on `main` with no changes to tracked files
   and, when the repository has a remote, equal to `origin/main`. If not, tell the user
   what differs; do not commit or push on your own.
3. **Snapshot the notes (owner).** `python scripts/snapshot_notes.py`: a dated zip of `live/` in
   `keeper/snapshots/` and a report of what changed since the last one. Read the report's first
   three sections to the user (author changed, conflict copies, review markers) when they are not
   empty. The index version records the snapshot's name. Skipped when nothing changed.
4. **Regenerate (only when the code pins in `sources.yaml` moved).**
   `bash scripts/regenerate.sh`: code checkouts, Gaia columns in the code, the
   `Software - <repo>` notes, then the checker. Stop on errors. The Gaia arm is built by
   hand with `scripts/build/` when a release or documentation version is added.
5. **Publish.** `HF_HUB_OFFLINE=1 python scripts/publish_index.py --publish`. It runs the
   checker (`--keeper`), takes `keeper/index/LOCK`, starts from the published index (or the
   local one the first time), embeds only what changed, archives the previous version
   (keeps 3), writes `keeper/index/current/`, appends a line to
   `keeper/index/history.jsonl`, and copies the result to `index/`.
   - It refuses when the embedding model or its revision changed: that needs a full
     rebuild (`python -m kb_pkg.index --rebuild`, about an hour) — ask the user first.
6. **Entry pages.** `python scripts/build/home.py`: Home, `Index - papers`, `Index - lessons`
   and one `Arm - <name>` page per arm, in `keeper/generated/`, from the notes' frontmatter.
   Run it after every publish (Home shows the index version). The search index skips these
   pages, so this does not make the index stale.
7. **Report** in a short table: version, passages (by source type and by arm), sources
   added / updated / removed, build time. Nothing goes to git: the history names private
   notes, so it stays in Keeper.

Roll back: `python scripts/publish_index.py --restore <version>` (the archived versions are
in `--status`). Then run step 6 and report as in step 7.

Never edit, move or delete files in `keeper/index/` by hand; the script holds the lock
while it writes. Never publish from a branch or with uncommitted changes to the code.
