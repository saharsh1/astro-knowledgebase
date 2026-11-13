---
name: consolidate
description: Merge the group's own notes on one topic (lessons, digests, discussion, work notes, across arms) into a new topic note that states the current view, the duplicates, the contradictions and what is superseded — without changing any source note. With no topic, list the topics worth consolidating. Use when the user says "/consolidate", "/consolidate <topic>", "merge the notes on X", "what do we know as a group about X", or "what should be consolidated".
---

# /consolidate [<topic>]

`/digest` summarises sources outside the group (papers, documentation, code).
`/consolidate` summarises the group's own notes. A topic note may cite digests.

## No topic: list candidates

`python scripts/consolidate.py candidates`. Show the top rows: the key (a column, a
repository or a tag), how many current notes are not yet in a topic note, which arms they
come from, and the topic note that covers it already. Ask which to consolidate. Write nothing.

## With a topic

1. **Find the notes**, and show the list before writing anything:
   - exact keys first: `python scripts/consolidate.py gather --applies-to <dr3:table.column | repo:name> [--tag ...]`;
   - then by meaning: `search_kb("<topic>", source_type="note")`, all arms, to find notes
     that name the topic differently. Add those with `--title-has` or by hand.
   The user confirms or trims the list.
2. **Read every note in full**, including the discussion files about it (`about:` it), and
   whether a later note supersedes it (the gather output says so).
3. **Write the draft** `outbox/<arm>/topics/Topic - <topic> - <author> - <YYYY-MM-DD>.md`
   from `templates/Topic.md`. The arm is the one most of the notes come from; other arms go
   in `arms:`. `author` = `git config github.user`. `consolidates:` lists every note used
   as `"[[stem]]"`. If gather named an existing topic note on this, add
   `supersedes: ["[[<latest topic note>]]"]` — this is a new version, never an edit.
   Sections:
   - **Current state**: what the group holds now, one claim per bullet, each cited to its
     source note(s) as [[stem]].
   - **Duplicates**: notes that say the same thing.
   - **Contradictions**: notes that disagree, side by side, with author and date. Report
     them; never decide which is right.
   - **Superseded**: notes a later note replaces.
   - **Open questions**.
   - **Sources consolidated**: the list, with authors.
   Keep the AI-generated callout. Plain short sentences; no claim without a [[source]].
4. `python scripts/check_vault.py --draft <draft> --dest live/<same path>`, fix, then show
   the user the draft and the authors whose notes it merges.
5. `/publish`. Then suggest the user asks those authors to confirm by a discussion file
   (`about:` the topic note). Never edit a source note, and never mark it yourself: the
   generated Home and indexes show "consolidated into" from `consolidates:`.
