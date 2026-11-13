---
name: resolve
description: Settle Seafile conflict copies — when two machines changed the same file between syncs, Seafile saves one version as "<name> (SFConflict <who> <when>)". Show each copy next to its original and let the author choose; never merge on your own. Use when the user says "/resolve", "conflict copies", or the session-start note or the checker reports SFConflict files.
---

# /resolve

1. `python scripts/resolve_conflicts.py` lists the copies, each marked "identical",
   "yours to settle" or "for <author> to settle".
2. Identical copies hold nothing new: offer to drop them all
   (`--keep original <copy>` for each).
3. For each copy that is yours: `python scripts/resolve_conflicts.py --show <copy>` and show
   the user the differences, in plain words (what each version says). Ask which to keep:
   - the original: `--keep original <copy>`;
   - the copy: `--keep copy <copy>`;
   - both, merged: the user says how; edit the original (you may, since its author is the
     user), show the result, then `--keep original <copy>`.
   Never choose for the user, and never merge without showing the merged text first.
4. A copy that is another member's: do not touch it. Tell the user whose it is, so they can
   tell that person.
5. Report what was settled. Dropped files are in `.resolve-trash/<date>/` (local) until the
   user deletes them.

Conflicts in `keeper/` (data, generated notes, locks) are the owner's to settle.
