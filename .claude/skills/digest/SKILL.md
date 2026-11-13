---
name: digest
description: Write a digest of a topic from the knowledge base — what the curated papers, the Gaia documentation, the group's code and the lessons say about it — as a draft note with every claim cited, then /publish it. Use when the user says "/digest <topic>", "summarize what we have on X", "what do the papers say about X".
---

# /digest <topic>

1. **Gather**, keeping what each source says with its location:
   - `search_kb("<topic>", source_type="paper")` — two or three phrasings; `author=` for key authors.
   - `lookup_column` / `find_columns` when the topic involves Gaia columns.
   - `search_kb("<topic>", source_type="code")` and the code cards in `live/code/`.
   - `search_kb("<topic>", source_type="note")`, all arms, and the lessons in `live/*/lessons/`.
2. **Check before writing:** open the cited page for every claim you keep (`get_neighbors`,
   or the PDF in `keeper/pdfs/`). Drop what the page does not support. Note disagreements.
3. **Write** `outbox/<arm>/notes/Digest - <topic> - <author> - <YYYY-MM-DD>.md`:
   frontmatter from `templates/Note.md` (`author` = `git config github.user`, `arms:` for
   other arms that should find it, tags allowed for its arms). Start with the AI-generated
   callout (model, date, index version from `index/index_meta.json`). Sections: **In short**,
   **What the sources say** (one bullet per claim, cited as [[paper note|Author year]], p. N),
   **In the code**, **Open questions / disagreements**, **Sources searched**.
   A digest that replaces an older one has `supersedes:` with a link to it.
   The arm: `gaia` for what the Gaia data and documentation say (e.g. the DR4
   non-single-star selection criteria); a science arm for the science. A `gaia` digest
   cites papers and Gaia notes only, never notes of a science arm.
4. Plain short sentences; numbers with units and their source; no claim without a citation.
5. Show the note, then `/publish`. Offer `/lesson` for any pitfall found.
