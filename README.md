# Astro knowledge base

Welcome. This is the shared knowledge base of our group: what we have read, what the Gaia
documentation says, what our code does, and what we have learned the hard way, in one place
that you can read in Obsidian and question with Claude.

**New here? Go to [docs/install.md](docs/install.md).** It takes about 20 minutes.

## What you can do with it

Ask Claude, in plain words, inside this folder:

- *"What does `ruwe` mean, and in which tables is it?"* The answer comes from the Gaia data
  model itself: type, unit, description, and where our papers and code use the column.
- *"How were the astrometric orbits in DR3 validated?"* Claude searches the Gaia
  documentation and the data-release papers, and cites the paper, section and page.
- *"Which of our codes fits an orbit to radial velocities?"* It searches the group's
  repositories too.
- *"Write a digest of what we have on the parallax zero point."* You get a note with every
  claim cited, to share with the group.
- *"Remember this for the group: ..."* A pitfall or a trick becomes a signed, dated lesson
  that everyone can find later.

## What is in it

| Part | Holds |
|---|---|
| **Gaia** | The DR3 documentation and data model, the DR4 draft data model (the formal one follows at the release), and the 57 data-release papers of DR3 and EDR3 |
| **Software** | The group's code repositories, each pinned to a commit: what they do and which Gaia columns they read |
| **Science arms** | Our own notes, lessons and digests on binary stars, the Milky Way and hot stars. These grow as we write |
| **Papers** | One note per paper, shared by all arms |

Only public material is here: released documentation and published papers. No unreleased
data and no internal documents.

## How it is put together

Three places, and you need all three:

| Place | Holds | Who writes |
|---|---|---|
| **This git repository** | The rules, scripts, templates and Claude skills: the skeleton | The owner; anyone can propose a change |
| **Keeper library `astro-kb-data`** (folder `keeper/`) | PDFs, the Gaia documentation, the search index | The owner and curators; members read |
| **Keeper library `astro-kb-notes`** (folder `live/`) | The group's notes | Every member |

The notes and data are not in this repository. Keeper syncs them to your machine, and a
note you publish reaches everyone within minutes. The search runs on your own machine;
nothing is sent to a service.

## Everyday commands

Say these to Claude:

| You want to | Say |
|---|---|
| start a session up to date | `/sync` |
| record something the group should know | `/lesson`, then `/publish` |
| a cited summary of a topic | `/digest <topic>`, then `/publish` |
| have a paper added | `/request-paper <arXiv id or DOI>` |
| merge the group's notes on one topic | `/consolidate <topic>` |
| propose a change to scripts, templates or rules | `/share` |
| settle a conflict copy made by Keeper | `/resolve` |

## Four rules from the first day

1. **Public material only.** No unreleased Gaia data, no internal DPAC documents.
2. **Notes reach the group through `/publish`,** which checks them first. Do not save new
   notes straight into `live/`.
3. **One writer per note.** Do not edit someone else's note; add to its discussion.
4. **Calculations and notebooks go in `sandbox/`,** which is never shared.

The full rules are in [CLAUDE.md](CLAUDE.md); Claude reads them at the start of every session.

## If something does not work

```bash
python scripts/doctor.py
```

It changes nothing and says, line by line, what is missing. If that does not settle it,
ask the owner.

## More

- [docs/install.md](docs/install.md): install it, add a member, the roles.
- [docs/status.md](docs/status.md): what was built and how it is tested, for maintainers.
- [docs/design/](docs/design/): the design and the reasons behind it.

Licences: MIT for the code (`LICENSE`), CC BY 4.0 for the text (`LICENSE-docs.md`).
