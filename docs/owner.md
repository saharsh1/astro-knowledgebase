# Owner's page: set up the knowledge base, add and remove members

What the **owner** does: once for the whole knowledge base, and once for each new member.
A member's own steps are in [install.md](install.md).

"The Seafile client" is the desktop program that syncs Keeper libraries.

## Once

1. **GitHub.** Create the repository `astro-knowledgebase` (empty), then from the clone:
   `git remote add origin <url>` and `git push -u origin main`. This is the only direct push
   to `main`.
2. **Protect `main`** (Settings → Branches → Add rule for `main`): require a pull request,
   require the status check `check`, require review from Code Owners. Allow squash merges
   only, and delete branches after the merge (Settings → General → Pull Requests). On a
   private repository of a free account GitHub does not enforce the branch rules; they take
   effect when the repository is public (or on a paid plan). Until then the rule is kept by
   agreement: nobody pushes to `main`.
3. **Keeper.** On <https://keeper.mpdl.mpg.de> create two libraries, `astro-kb-data` and
   `astro-kb-notes`. In the Seafile client choose "sync with an existing folder" and point
   them to `astro-knowledgebase/keeper` and `astro-knowledgebase/live`. Wait until both
   show as synced.
4. **Roles.** `keeper/roles.yaml` (in Keeper, not in git, because the member list is
   private):

   ```yaml
   curators: [github-name-1, github-name-2]    # may add papers with /ingest
   index_keepers: []                           # may publish the search index; the owner always may
   ```

   The file only tells the skills what to offer a person (`/ingest` to a curator,
   `/request-paper` to everyone else). The real lock is Keeper: without a Read-Write share of
   `astro-kb-data` nobody can add a paper or publish the index. If you do both jobs
   yourself, leave the two lists empty.

## For each new member

Ask the member for their **GitHub user name** and their **Keeper account** (the e-mail
address they log in to Keeper with). Then:

1. **GitHub** (only while the repository is private; a public repository needs nothing):
   Settings → Collaborators → Add people → the GitHub user name, role **Read**. A member
   with Read can clone and pull. To propose changes with `/share` they need **Write** (to
   push a branch); `main` stays protected by the rules above.
2. **Keeper, data:** library `astro-kb-data` → Share → the member's account → **Read-Only**.
3. **Keeper, notes:** library `astro-kb-notes` → Share → the member's account → **Read-Write**.
4. **Curator or index keeper?** Two steps, and both are needed:
   - add their GitHub user name to `curators:` (or `index_keepers:`) in `keeper/roles.yaml`;
   - change their share of `astro-kb-data` to **Read-Write**: adding a paper or publishing
     the index writes into that library.
5. Send them [install.md](install.md).

When a member has finished, their first `/lesson` → `/publish` should reach your machine
within minutes; `/sync` on your side shows the new note count.

## Removing a member

Remove the two Keeper shares and the GitHub collaborator, and take the name out of
`keeper/roles.yaml`. Their notes stay.

## Regular jobs

| Job | How |
|---|---|
| publish the search index, with a snapshot of the notes and fresh entry pages | `/publish-index` |
| add papers that members asked for | `/ingest` |
| review a proposed change to the skeleton | the pull request on GitHub; merge with "Squash and merge" |
| pin a note on Home | `pinned: true` in the note's frontmatter, then `/publish-index` |
