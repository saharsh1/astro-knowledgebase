---
name: ingest
description: Curators only — add papers to the knowledge base (PDF and lock into Keeper, paper and BibTeX notes through outbox/), directly or from members' requests. Use when the user says "/ingest", "ingest the requests", "add <arXiv id> to the knowledge base", and the user is a curator.
---

# /ingest [<ids> | --requests]

1. Check the role: `git config github.user` must be the owner or in `curators:` of
   `keeper/roles.yaml`. If not, stop and offer `/request-paper`.
2. Choose the papers:
   - `--requests` (or "the requests"): `python scripts/ingest_paper.py --list-requests`,
     show the open requests (id, arm, who, why), and ask which to ingest.
   - ids given: ask for the arm if the user did not say.
     Gaia Collaboration and DPAC papers (data release, validation, documentation
     papers) take the arm `gaia`; papers that use Gaia for science take the science arm.
3. Rule 1 (public material only): the script fetches only publisher open access or arXiv.
   For `--pdf <file>`, ask the user to confirm the copy is public before running it.
4. Run `python scripts/ingest_paper.py --request <request files>` or
   `python scripts/ingest_paper.py <ids> --arm <arm> [--tags ...]`.
   Tags: common tags or tags of the arm (`conventions.yaml`).
5. Publish the notes it wrote: `python scripts/publish_notes.py --apply --only <outbox/papers/... files>`.
6. Refresh the index: `cd scripts && HF_HUB_OFFLINE=1 python -m kb_pkg.index`.
7. Report: each paper, its PDF source (or none), and the requests now done.

To decline a request (e.g. the paper is not public), write a discussion file in
`outbox/<arm>/discussion/` with `about:` the request and the word "Declined" and the
reason, then /publish it. Never edit or delete the request note itself.
