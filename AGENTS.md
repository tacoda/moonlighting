# AGENTS.md — moonlighting

A software factory. Humans work the day shift (deciding), pi agents work the
night shift (doing). Work moves through the factory as **work orders**: small
markdown files in `work-orders/` whose `status:` frontmatter line is the
contract between shifts.

## Layout

- `work-orders/<sha>-short-title.md` — one file per unit of work. Each order carries a unique 7-char sha id
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

<!-- BEGIN nWave-beta-section (managed by nwave-ai; do not edit) -->

## nWave (beta) — How to Work in This Project

Three routes are open to a Request:
- Spine waves (whole-feature default): wave gates, independent review and
  source-blind EXAMINE where applicable; durable authorities. Evolution retains
  lasting facts; integration closes delivered work.
- Host-led nwdes steps: the root runs roles with generated prompts. Roles record
  typed values with kind verbs and close. nwdes builds and
  writes authority/run records; the host submits/retains no role reply.
  Public oracle before code; nwdes launches no model. Details: nw-nwdes and nwdes --help.
- Working directly: fastest; nothing attests the result.

The LLM chooses the route by what survives and the cost of late refusal,
and invokes the applicable waves. The final whole-candidate review and integration happen once per Request; embedded per-slice refinement reviews provide early feedback, not final approval.
Each Request opens with the LLM's working S/M/L assessment and why, which never decides the route.
The LLM revises it as evidence changes and suggests the fastest route that
keeps what must survive; the user decides scope and trade-offs.
Working directly remains open when little must survive.
Human WIP limit: 2. Finish open work before starting new work.
One close receipt closes only that invocation: keep ready work moving; a refused close is unfinished work.
When a review or EXAMINE rejects work, or new work is ready, the Lane flow
of the nw-throughput skill holds what comes next.
Whichever route this Request takes, say which one.

nWave is in **active development**.

DISCUSS/DESIGN resolve only real gaps. Human authority decides genuine scope/trade-offs.

Several lanes in parallel: skill `nw-swarm` (a host without skill loading reads its `SKILL.md` from the installed skills folder).

**Batch independent tool calls in one turn (one per turn is a violation); sequence only when one result feeds the next.**

### Asking the User a Question

Fixed shape, every time: **context** -> **recommendation** -> **options** (each
with its consequence/risk) -> one direct question. Real section headers and
bold labels — never a wall of text. User-facing output follows **ASD-STE100**
(Simplified Technical English).

Owner answer pending: independent ready work continues; only dependent work waits. Boundary and durable record: `nw-auto` §4.

### Privacy — Non-Negotiable

nWave stores workflow data locally and collects no telemetry. Jev, a remote question service, is on by default for supported questions and sends only permitted data classes; switch it with `"jev": "authorized"` or `"jev": "unauthorized"` in `.nwave/config.json`. `TYPESAFE_API_KEY` is only Jev's technical prerequisite, not its authorization. See [PRIVACY.md](../../PRIVACY.md) for the complete policy. Feedback on nWave itself is welcome via GitHub Issues on the experimental repo, at your discretion — never a required step of doing the work.

<!-- END nWave-beta-section -->

