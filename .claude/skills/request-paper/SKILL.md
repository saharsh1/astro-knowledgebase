---
name: request-paper
description: Ask the curators to add a paper to the knowledge base. Use when the user says "/request-paper", "add this paper", "can we get <arXiv id/DOI>", or when a member who is not a curator wants a paper ingested.
---

# /request-paper <arXiv id | DOI | bibcode | URL>

Members request; curators ingest (rule 5). If the user is a curator
(`git config github.user` is the owner or in `curators:` of `conventions.yaml`), offer
`/ingest` instead.

1. Ask for what is missing: the arm (from `conventions.yaml`) and one line on why the
   group needs the paper.
2. `python scripts/request_paper.py <id> --arm <arm> --reason "<why>"`.
   It stops if the paper is in the knowledge base already or someone has an open request
   for it: tell the user where.
3. Publish the request: `python scripts/publish_notes.py --apply --only <file it wrote>`.
4. Tell the user the request is in `live/requests/` and that a curator will ingest it.
   `python scripts/request_paper.py --list` shows every request and its state.

A request holds identifiers only. Never attach or download a PDF for a request.
