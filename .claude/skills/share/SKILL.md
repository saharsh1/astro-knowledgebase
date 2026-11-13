---
name: share
description: Propose a change to the skeleton of the astro knowledge base (rules, scripts, templates, skills, code pins in sources.yaml, demos, docs) as a pull request to the owner — check, commit on a branch, push after the user's yes, open the pull request. Use when the user says "/share", "open a PR", "propose this change", or after editing scripts, templates or sources.yaml. Notes, lessons and digests are not shared this way: they go to live/ with /publish.
---

# /share

The skeleton is public and changes only by pull request; the owner reviews and merges
(rule 7). Notes never go into git: if the user wants to share notes, use `/publish`.

Run from the repository root with the knowledge base's Python (the `bskb` environment).

1. **What changed.** `python scripts/share.py` lists the changed files. Give the user one
   line per file. Ask which to include when a file looks unrelated (a calculation belongs
   in `sandbox/`, which git ignores). A data file, PDF, image or anything personal never
   goes in: it belongs in Keeper.
2. **Message.** Write the commit message to `sandbox/share-message.txt` (git ignores it):
   a short subject line, a blank line, what changed and why, then the attribution lines
   the session requires.
3. **Commit.** `python scripts/share.py --commit --topic "<two to four words>"
   --message-file sandbox/share-message.txt [paths ...]` (no paths: every changed file).
   From `main` it makes the branch `<github user>/<date>-<topic>`; on another branch it adds a
   commit there. It runs the public-repository guard, the checker (skeleton only) and the
   tests the GitHub check runs, and commits only when all pass. On a failure nothing is
   committed and the clone is as it was: fix what the output names, and run step 3 again.
   Never fix a failure by weakening a check or a test.
4. **Push, after the user's yes.** Say the branch name and that the repository is public:
   the files will be visible to anyone. With a yes: `python scripts/share.py --push`. It
   opens the pull request with `gh` when it is signed in, else it prints the link.
5. **Report** the branch, the pull request (or link), and what happens next: the GitHub
   check runs, the owner reviews and merges (squash). After the merge, everyone gets the
   change with `/sync`; when it touches the indexing code or the pins, the index keeper
   runs `/publish-index`.

Never push `main`, never force-push, never commit files in `live/`, `keeper/`, `outbox/`,
`sandbox/`, `index/` or `external/`.
