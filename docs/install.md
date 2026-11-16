# Install the astro knowledge base

This page is for a **member** who installs the knowledge base on their own machine. The
owner's steps (creating the libraries, adding a member, roles) are in [owner.md](owner.md).

**Time:** your own actions take about 15 minutes. The downloads take longer: plan about an
hour in total, and let them run while you do something else.

**Disk:** about 6 GB.

**System:** macOS or Linux. Windows is not tested.

## What you will have at the end

One folder, `astro-knowledgebase`, with three parts that come from three places:

| Part of the folder | Holds | Comes from |
|---|---|---|
| the folder itself | rules, scripts, templates: the skeleton | GitHub (`git clone`) |
| `keeper/` | PDFs, the Gaia documentation, the search index. You read it; you do not change it | Keeper library `astro-kb-data` |
| `live/` | the group's notes. Everyone writes here, through `/publish` | Keeper library `astro-kb-notes` |

You open this one folder in Obsidian to read, and in Claude Code to ask questions.

## Before you start

**1. Send the owner two names:** your GitHub user name, and the e-mail address of your
Keeper account. The owner invites you. You then get:

- an e-mail from GitHub: accept the invitation (only needed while the repository is private);
- two libraries in Keeper, `astro-kb-data` and `astro-kb-notes`. Log in at
  <https://keeper.mpdl.mpg.de> and look under "Shared with me". If they are not there, stop
  and ask the owner.

**2. Install five programs.** Skip the ones you have.

| Program | For | Get it from | Check that it works |
|---|---|---|---|
| git | fetching the skeleton | macOS: it installs itself the first time you type `git` in a terminal. Linux: your package manager | `git --version` prints a version |
| Miniforge (conda) | the Python environment | <https://conda-forge.org/download/> | open a **new** terminal; `conda --version` prints a version |
| Seafile client | syncing the two Keeper libraries | <https://www.seafile.com/en/download/>: the **Desktop Syncing Client**, not "SeaDrive", and the version without Shibboleth | it opens and asks for a server |
| Obsidian | reading the notes | <https://obsidian.md> | it opens |
| Claude Code | asking questions | <https://claude.com/claude-code> (the desktop app or the terminal program) | it opens and you are signed in |

Keeper is the Max Planck service; the Seafile client is the program that syncs it. This
page calls the program "the Seafile client" everywhere.

**3. Sign the Seafile client in to Keeper.** In the client choose "Add an account":
server `https://keeper.mpdl.mpg.de`, then your Keeper e-mail address and password. You
should now see the two libraries in the client's list.

## Step 1. Get the skeleton from GitHub

Open a terminal. Go to the folder where the knowledge base should live. Do **not** put it
inside Dropbox, iCloud, OneDrive or another synced folder: two sync programs on the same
files make conflicts.

While the repository is private, GitHub must know who you are. The simplest way is
GitHub's own command-line program:

```bash
conda install -y -c conda-forge gh
```

```bash
gh auth login
```

Answer its questions: `GitHub.com`, `HTTPS`, "Yes" to authenticate git, "Login with a web
browser". Then:

```bash
gh repo clone saharsh1/astro-knowledgebase
```

(Once the repository is public, or if git on your machine is already signed in to GitHub,
`git clone https://github.com/saharsh1/astro-knowledgebase.git` does the same.)

```bash
cd astro-knowledgebase
```

**You should see** a folder `astro-knowledgebase` with `README.md`, `CLAUDE.md`, `scripts/`
and `docs/` in it. There is no `keeper/` and no `live/` yet. Stay in this folder for the
rest of the page.

## Step 2. Sync the two Keeper libraries into it

This is the step where things most often go wrong, so check the result before you go on.
Each library must land **exactly** in its folder, not in a folder inside it.

First make the two empty folders:

```bash
mkdir keeper live
```

Then, in the Seafile client, for each library:

1. Right-click the library and choose "Sync this library".
2. In the window that opens, choose "sync with an existing folder" (a small link in that
   window), and pick the folder from this table.
3. Confirm.

| Library | Folder to pick |
|---|---|
| `astro-kb-data` | `astro-knowledgebase/keeper` |
| `astro-kb-notes` | `astro-knowledgebase/live` |

The wording in your version of the client may differ a little. What matters is the result.

Wait until the client shows both libraries as synced. `astro-kb-data` is about 2 GB.

**Check the result:**

```bash
ls keeper live
```

**You should see** `pdfs`, `parsed`, `generated`, `index` and `locks` among the names under
`keeper`, and `papers`, `gaia` and `binary-stars` among those under `live`.

**If you see `keeper/astro-kb-data/` or `live/astro-kb-notes/` instead:** the library went
one level too deep. In the Seafile client, right-click the library, choose "Unsync", delete
that inner folder, and do the step again with "sync with an existing folder".

Keeper puts two files of its own at the top of every library (`archive-metadata.md` and
`Cared-Data-Certificate-HowTo.pdf`). Leave them.

## Step 3. Run the setup

```bash
bash scripts/setup.sh
```

It asks one question: your GitHub user name. Then it works alone, in eight numbered steps:

- it creates the Python environment `bskb` (a few minutes);
- it downloads the search model (1.3 GB, once per machine);
- it fetches the group's code and copies the published search index;
- it bookmarks the entry pages in Obsidian;
- it ends with the **doctor**: a list of checks, one line each.

**You should see** every doctor line start with `OK`, and a last line with `0 FAIL`.

**If a line says WARN or FAIL:** the line itself says what to do. Do it, then run
`bash scripts/setup.sh` again. It is safe to run as often as you like: it skips what is done.

## Step 4. Open the folder in Obsidian

In Obsidian: "Open folder as vault", and pick `astro-knowledgebase`.

Click the bookmark icon in the left panel. **You should see** eight bookmarks: Home, Papers,
Lessons, and one per arm (Gaia, Software, Binary stars, Milky Way, Hot stars). Open **Home**:
it lists the arms, the newest lessons, the papers and the Gaia documentation.

## Step 5. Open the folder in Claude Code

Open `astro-knowledgebase` as the project folder. Claude Code asks once whether to allow the
search server `astro-kb`: say yes.

Try these two questions:

- "Look up the column ruwe in gaia_source."
- "What do we have on astrometric orbits?"

**You should see** for the first an answer with the column's type, unit and description, and
for the second an answer that names papers or documentation sections with their pages. Then
the installation is complete.

## Daily use

| You want to | Say to Claude |
|---|---|
| start a session up to date | `/sync` |
| record something the group should know | `/lesson`, then `/publish` |
| a summary of what the knowledge base says on a topic | `/digest <topic>`, then `/publish` |
| a paper added | `/request-paper <arXiv id or DOI>` |
| propose a change to scripts, templates or rules | `/share` |
| settle a conflict copy made by the Seafile client | `/resolve` |

Four rules matter from the first day. All rules are in `CLAUDE.md`.

- **Public material only.** No unreleased Gaia data, no internal DPAC documents.
- **Notes reach `live/` only through `/publish`**, which checks them first. Do not save new
  notes straight into `live/` from Obsidian. Write in `outbox/`, or let Claude draft there.
- **One writer per note.** Do not edit another member's note; add to its discussion.
- **Calculations and notebooks go in `sandbox/`**, which is never shared.

## When something does not work

Run the doctor, from the `astro-knowledgebase` folder:

```bash
conda run -n bskb python scripts/doctor.py
```

It changes nothing. It says, check by check, what is missing: the Python environment, the
search model, the two Keeper folders, the code, the search index, and whether the search
server answers. Each failing line says how to repair it.

| What you see | Likely cause | Do this |
|---|---|---|
| `gh repo clone` says the repository was not found | the GitHub invitation is not accepted yet | accept it (e-mail, or <https://github.com/notifications>), then clone again |
| `conda: command not found` | the terminal was open before Miniforge was installed | open a new terminal |
| the doctor says `keeper/` or `live/` is missing, or files are missing | the Seafile client is still downloading, or a library went one level too deep | wait for the sync; else see Step 2 |
| Claude does not offer the search tools | the server `astro-kb` was not allowed, or the session started before the setup ended | start a new Claude Code session in the folder and allow the server |
| anything else | | send the owner the doctor's output |
