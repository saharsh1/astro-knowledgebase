---
name: lesson
description: Record a communal lesson — a pitfall, tip, recipe or open question someone learned — as a signed, dated draft in outbox/, then /publish it. Use when the user says "/lesson", "remember this for the group", "add a lesson", or when a session finds something others should know.
---

# /lesson

1. Draft from the session: **What** (one or two sentences), **Why it matters**,
   **Evidence** (paper and page, documentation section, notebook, code file and line),
   **How to check** (a line of code or an ADQL query).
2. Choose the arm (`conventions.yaml`): the arm whose members need it most. Other arms
   that should find it go in `arms:`. **Which layer?** What the Gaia data or documentation
   says (a column, a flag, a unit, `corr_vec`, a selection criterion, a validation
   result) goes to `gaia`. A trap or tip in the group's code (with
   `applies_to: repo:<name>@<pin>`) goes to `software`. The science, or how a science
   question uses Gaia or the code (a paper's error, a mass from an orbit), goes to the
   science arm. Links run down only: science → software → gaia.
3. Frontmatter from `templates/Lesson.md`: `kind`, `status: current`,
   `author` = `git config github.user`, `created` and `last_checked` = today,
   `applies_to` (e.g. `dr3:nss_two_body_orbit.corr_vec`, `repo:<name>@<pin in sources.yaml>`),
   `tags` (common tags or tags of its arms).
4. Write `outbox/<arm>/lessons/<YYYY-MM-DD> - <author> - <short title>.md`. Add the
   AI-generated callout if Claude wrote the text.
5. Show the draft; the user corrects and approves it. Then `/publish`.

To answer or correct another member's lesson, never edit it (rule 2): write a discussion
file from `templates/Discussion.md` in `outbox/<arm>/discussion/`, or a new lesson with
`supersedes:`.
