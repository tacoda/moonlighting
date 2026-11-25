# Moonlighting — Plan

> **Status:** Phases 0–2 built and live with pi — four real runs executed
> end to end (wo-001..004, 2026-11-22). The first `--engine claude` run is
> still pending. Engines now: pi, claude and opencode. The factory is a uv
> project with a pytest suite (`uv run pytest`).

A software factory where **humans work the day shift** (deciding) and **agents work the night shift** (doing). Built on [pi](https://pi.dev), Claude Code and opencode as the night-shift workforce.

## The core idea

Work enters the factory as **work orders** — small markdown files with a status line. The status line is the contract between the two shifts:

- A work order marked `approved` is a standing instruction: the night shift may execute it autonomously.
- Anything else (`draft`, `blocked`, `review`, `done`, `rejected`) means "hands off" — it's waiting on a human decision.

The factory is just a git repo + a runner script + conventions. No server, no database, no UI. Git history is the audit log.

```
Day (human)                          Night (pi agent)
────────────                         ────────────────
write draft orders
review yesterday's diff  ◄────────   execute approved orders
approve / reject / block  ────────►  log sessions, flip status to review
```

## Work order lifecycle

```
draft ──► approved ──► review ──► done
              │           │
              ▼           ▼
           blocked ◄──────┘   (human answers question, re-approves)
              │
              └──► rejected
```

Work order file: `work-orders/NNN-short-title.md`

```markdown
---
id: NNN
title: Short title
status: approved        # draft | approved | review | blocked | done | rejected
created: YYYY-MM-DD
branch: wo/NNN          # branch the night shift works on
---

## Goal
What "done" means, in one or two sentences.

## Tasks
Concrete steps the night agent should take.

## Constraints
What the agent must NOT do, standards to follow.

## Night shift log      <!-- appended by the night runner -->
## Day shift decisions  <!-- appended by humans -->
```

## Phases

### Phase 0 — Factory floor (structure + conventions)  *~1 hour*

Everything is files and folders. No code yet.

- [x] `README.md` — the factory handbook: shifts, roles, lifecycle, how to run a night
- [x] `AGENTS.md` — standing instructions for any pi session that enters this repo (what a work order is, what it may touch, when to stop and set `blocked`)
- [x] `docs/work-order-template.md` — the template above
- [x] `night-shift/` — runner scripts and `logs/`
- [x] `docs/runbook.md` — day-shift checklist (what to review each morning) and night-shift checklist (how to kick off the run)

**Done.**

### Phase 1 — The night shift runs  *the MVP*

One script, one command, end-to-end.

- [x] `night-shift/run.py` (evolved beyond the sketch: engine `--engine pi|claude`, target repos via `repo:`, per-repo locks, WIP auto-commit sweep, output captured outside the working tree):
  1. Find work orders with `status: approved` (oldest first)
  2. For each (stopping after `--max-orders`, default 1):
     - create/checkout its `wo/NNN` branch in the order's target repo
     - run the engine headless with `NIGHT-SHIFT.md` as appended system prompt and the order embedded in the prompt
     - append the agent's final report to the order's *Night shift log*
     - flip `status: approved` → `status: review` (→ `blocked` on failure or dirty target)
     - self-repo: return to `main`; external targets: stay on the order branch
  3. Write a run summary to `night-shift/logs/YYYY-MM-DD.md`
- [x] `night-shift/NIGHT-SHIFT.md` — the agent's operating manual (in small scope, test before declaring done, never flip status itself, set `blocked` + a question in the log if stuck)

**Done:** live with pi — wo-001..004 ran end to end on 2026-11-22. The claude path ran against stub engines only.

### Phase 2 — The day shift decides  *make the loop a habit*

- [x] `day-shift/status.py` — factory floor report: queued orders, orders in review, branches awaiting merge, per-repo with locks
- [x] Decision conventions: a human reviews `wo/NNN`, then either
  - merges the branch and marks `done` (`day-shift/accept.py NNN`), or
  - sets `blocked` with a question for tonight, or
  - sets `rejected` with a reason
- [x] Squash-merge convention: the night agent must never merge; only day shift merges

**Built. Real cycles started 2026-11-22** (wo-001..004).

### Phase 3 — Hardening  *once the loop is trusted*

- [x] **Isolation** — pulled forward, live fire demanded it: every order runs
  in a throwaway `git worktree` under `night-shift/worktrees/` (removed after
  the run); working copies are never switched, so dirty targets no longer
  block; parallel orders in one repo become possible.
- [x] **Auditability** — every run archives the engine's full JSON event stream (`night-shift/logs/*.events.jsonl`, `*.qa.jsonl`); the final report is extracted from it
- [x] **Validation** — `night-shift/lint-order.py` for the day shift; the runner lint-blocks approved malformed orders before spending tokens
- [x] **Scheduling** — `night-shift/schedule.py install|remove|status`; nightly cron, harmlessly no-ops on an empty queue
- [~] **Budget rails**: per-order time cap done (`NIGHT_TIMEOUT_SECS`, default 7200s → killed and marked blocked); token cap — now unblocked, since usage data lives in the archived event streams (parse, abort, mark blocked)
- [ ] **Log rotation** — `logs/` and `cron.log` grow forever; rotate or cap someday (small)
- [ ] **Claude engine live-fire** — implemented and stub-tested. The first real `--engine claude` order is still pending.
- [ ] **Multi-machine locks** — pid locks are machine-local; factories on different machines targeting the same repo won't collide-detect (per-repo clone pattern sidesteps this; revisit only for multi-box setups)
- [ ] **Secrets framework** — beyond the night manual's “never commit secrets” rule: decide what credentials agents may see, and how

### Phase 4 — Expansion  *only if the loop proves out*

The loop proved out. Pulled forward and shipped:

- [x] **QA pre-shift** — a second agent pass reviews every night's diff and writes a SHIP/BLOCK/UNSURE verdict into the order file (opt out: `FACTORY_QA=0`)
- [x] **Multi-repo** — orders name a target repo (`repo:` path or git URL, cloned under `repos/`); day shift merges and pushes target repos themselves
- [x] **Parallel shifts** — one factory process per repo, each in its own clone, launched concurrently; worktree isolation + locks make it safe (proven live)
- [x] **Claude Code engine** — same flow, `--engine claude`, sessions tracked per order
- [x] **opencode engine** — same flow via `--engine opencode`. The host picks the session id (`ses_...`) and the runner keeps it in `night-shift/sessions.json`

Still open:

- [ ] **Skills** for recurring job types ("add a CLI command", "write a migration") loaded via `pi --skill`. Deferred until real nights show the recurring job types
- [ ] **Prompt templates** for authoring work orders consistently. Deferred until the order format settles
- [x] **Morning report** — the night writes `logs/YYYY-MM-DD-morning.md` with review and blocked orders and their latest QA verdicts

## Scope discipline (what "minimal" means)

In scope for now: **Phases 0–2 only.** Plain Python (stdlib) + markdown.
Hosts: pi and Claude Code (engine per run), both under the nWave guard.
Orders may target external repos; one factory process per repo. One order per night run by default.

Explicitly out of scope until Phase 3+: worktrees (done), JSON event archives (done), cron (done), token budgets (pending, see Phase 3), parallel orders within one repo. Every phase must leave the factory usable on its own — no half-built scaffolding.

**Build pause.** The machinery is done; the next feature should come from a real night's friction, not speculation. Run the factory for a month, then revisit this list.

## Risks & guardrails (baked in from Phase 1)

| Risk | Guardrail |
|---|---|
| Agent merges its own work | Merging is a day-shift-only convention; night runner never merges |
| Agent runs away on a vague order | Night manual: if acceptance criteria are unclear → set `blocked`, ask a question, stop |
| Secrets/credentials exposed to the agent | Orders reference files, never inline secrets; `.env`-style files gitignored from day one |
| Night run corrupts the repo | Each order works on its own branch in its own worktree; `main` only moves via day-shift merges |
| Two machines, same target repo | Locks are machine-local — out of scope by design; keep one factory (on one machine) per target repo |
| Silent failures | The runner records every order attempt in `night-shift/logs/` and never deletes logs. Pre-flight failures land in the gitignored `night-shift/logs/errors.log` |
