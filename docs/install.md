# Install the astro knowledge base

Two parts: what the **owner** does once (and once per new member), and what each **member**
does on their machine. A member needs about 20 minutes, most of it waiting for downloads.

The knowledge base has three places:

| Place | Holds | You get it by |
|---|---|---|
| The git repository `astro-knowledgebase` (GitHub) | rules, scripts, templates, skills: the skeleton | `git clone` |
| Keeper library `astro-kb-data` → folder `keeper/` | PDFs, Gaia documentation, the search index; read-only for members | the Keeper desktop client |
| Keeper library `astro-kb-notes` → folder `live/` | the group's notes; everyone writes | the Keeper desktop client |

## Owner: once

1. **GitHub.** Create the repository `astro-knowledgebase` (empty), then from the clone:
   `git remote add origin <url>` and `git push -u origin main`. This is the only direct push
   to `main`.
2. **Protect `main`** (Settings → Branches → Add rule for `main`): require a pull request,
   require the status check `check`, require review from Code Owners, allow squash merges
   only (Settings → General → Pull Requests). On a private repository of a free account
   GitHub does not enforce these rules; they take effect when the repository is public (or
   on a paid plan). Until then the rule is kept by agreement: nobody pushes to `main`.
3. **Keeper.** In the Keeper web page create two libraries, `astro-kb-data` and
   `astro-kb-notes`. In the desktop client choose "Sync with an existing folder" and point
   them to `astro-knowledgebase/keeper` and `astro-knowledgebase/live`. Wait until both
   show as synced.
4. **Roles.** Write `keeper/roles.yaml` by hand (it is in Keeper, not in git, because the
   member list is private):

   ```yaml
   curators: [github-name-1, github-name-2]    # may add papers with /ingest
   index_keepers: []                           # may publish the search index; the owner always may
   ```

## Owner: for each new member

Ask the member for their **GitHub user name** and their **Keeper account** (the e-mail
address they log in to Keeper with). Then:

1. **GitHub** (only while the repository is private; a public repository needs nothing):
   Settings → Collaborators → Add people → the GitHub user name, role **Read**. A member
   with Read can clone and pull. To propose changes with `/share` they need **Write** (to
   push a branch); `main` stays protected by the rules above.
2. **Keeper, data:** library `astro-kb-data` → Share → the member's account → **Read-Only**.
3. **Keeper, notes:** library `astro-kb-notes` → Share → the member's account → **Read-Write**.
4. **Curator?** Add their GitHub user name to `curators:` in `keeper/roles.yaml`.
5. Send them this page.

Removing a member: remove the two Keeper shares and the GitHub collaborator, and take the
name out of `keeper/roles.yaml`. Their notes stay.

## Member: on your machine

You need: git, [Miniforge](https://conda-forge.org/download/) (conda), the Keeper desktop
client, [Obsidian](https://obsidian.md) and Claude Code. About 6 GB of disk: 2 GB for the
Keeper data, 1.3 GB for the search model, the rest for the Python environment.

1. **Accept the invitations**: the GitHub invitation (by e-mail, while the repository is
   private) and the two Keeper shares (they appear under "Shared with me").
2. **Clone the skeleton:**

   ```bash
   git clone https://github.com/saharsh1/astro-knowledgebase.git
   ```

3. **Sync the two Keeper libraries into the clone.** In the Keeper desktop client, for each
   library choose "Sync this library" and set the folder so that the library lands exactly
   here (create the two empty folders first and use "Sync with an existing folder"):

   | Library | Folder |
   |---|---|
   | `astro-kb-data` | `astro-knowledgebase/keeper` |
   | `astro-kb-notes` | `astro-knowledgebase/live` |

   Wait until both are synced (about 2 GB).
4. **Run the setup** from the clone. It asks for your GitHub user name once:

   ```bash
   bash scripts/setup.sh
   ```

   It creates the Python environment `bskb`, writes `scripts/config.local`, installs a
   check that runs before each commit, downloads the search model (1.3 GB), copies the
   published search index, and ends with the doctor: one line per check. Every line should
   say OK. A WARN or FAIL line says what to do; run the setup again after fixing it.
5. **Open the folder in Obsidian** ("Open folder as vault" → `astro-knowledgebase`).
6. **Open the folder in Claude Code** and approve the search server `astro-kb` when asked.
   Try: "look up the column ruwe in gaia_source" and "what do we have on astrometric orbits?".

## Daily use

| You want to | Say to Claude |
|---|---|
| start a session up to date | `/sync` |
| record something the group should know | `/lesson`, then `/publish` |
| a summary of what the knowledge base says on a topic | `/digest <topic>`, then `/publish` |
| a paper added | `/request-paper <arXiv id or DOI>` |
| propose a change to scripts, templates or rules | `/share` |
| settle a Seafile conflict copy | `/resolve` |

Rules that matter from the first day (all of them are in `CLAUDE.md`):

- **Public material only.** No unreleased Gaia data, no internal DPAC documents.
- **Notes reach `live/` only through `/publish`**, which checks them first. Do not save new
  notes straight into `live/` from Obsidian; write in `outbox/` or let Claude draft there.
- **One writer per note.** Do not edit another member's note; add to its discussion.
- **Calculations and notebooks go in `sandbox/`**, which is never shared.

## When something does not work

```bash
python scripts/doctor.py
```

It changes nothing and says, check by check, what is missing: the Python environment, the
search model, `scripts/config.local`, the two Keeper folders, the code checkouts, the
search index, and whether the search server answers.
