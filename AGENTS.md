# AGENTS.md — moonlighting

A software factory. Humans work the day shift (deciding), pi agents work the
night shift (doing). Work moves through the factory as **work orders**: small
markdown files in `work-orders/` whose `status:` frontmatter line is the
contract between shifts.

## Layout

- `work-orders/NNN-short-title.md` — one file per unit of work; ids zero-padded to 3 digits
- `night-shift/run.py` — executes approved orders headlessly via pi
- `night-shift/NIGHT-SHIFT.md` — the night agent's operating manual
- `day-shift/status.py` — floor report · `day-shift/accept.py NNN` — squash-merge an order into its target repo
- `repos/` — target repos cloned from git URLs (gitignored)
- `docs/runbook.md` — shift checklists · `docs/work-order-template.md` — order template · `PLAN.md` — roadmap

## Status lifecycle

```
draft → approved → review → done
             │         │
             ▼         ▼
          blocked ◄────┘        rejected (from anywhere)
```

Only humans move work into or out of `approved`, `blocked`, `done`, `rejected`.
The night runner moves `approved → review` (or `→ blocked` when a run fails).

## Rules for agents in this repo

- Execute only orders whose status is `approved`, only through the night-shift flow.
- Work on the order's own branch (`wo/NNN`). Never merge, never push, never commit to `main`.
- Never edit order files — not statuses, not logs, not decision sections.
  Those belong to humans and the runner. Reading orders is expected.
- An order may target another repo (`repo:` field). The runner places you in
  a throwaway git worktree of that repo with your branch checked out — the
  same rules apply there: never `main`, never push, never touch order files.
- Unclear order? Stop and report BLOCKED. Never guess.
- Humans append answers under an order's *Day shift decisions* section and
  re-approve blocked orders; re-read the order file at the start of every run.
