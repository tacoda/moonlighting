# Moonlighting — Plan

A software factory where **humans work the day shift** (deciding) and **agents work the night shift** (doing). Built on [pi](https://pi.dev) as the night-shift workforce.

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

- [ ] `README.md` — the factory handbook: shifts, roles, lifecycle, how to run a night
- [ ] `AGENTS.md` — standing instructions for any pi session that enters this repo (what a work order is, what it may touch, when to stop and set `blocked`)
- [ ] `work-orders/000-work-order-template.md` — the template above
- [ ] `night-shift/` — runner scripts and `logs/`
- [ ] `docs/runbook.md` — day-shift checklist (what to review each morning) and night-shift checklist (how to kick off the run)

**Done when:** the repo explains itself; a human can write a work order and know exactly what `approved` commits them to.

### Phase 1 — The night shift runs  *the MVP*

One script, one command, end-to-end.

- [ ] `night-shift/run.py`:
  1. Find work orders with `status: approved` (oldest first)
  2. For each (stopping after `--max-orders`, default 1–3):
     - create/checkout its `wo/NNN` branch from `main`
     - run `pi --print --approve --session-id wo-NNN @work-orders/NNN-*.md` with `--append-system-prompt night-shift/NIGHT-SHIFT.md`
     - append the agent's final report to the order's *Night shift log*
     - flip `status: approved` → `status: review`
     - leave the working tree on `main`, uncommitted night work lives on the order's branch
  3. Write a run summary to `night-shift/logs/YYYY-MM-DD.md`
- [ ] `night-shift/NIGHT-SHIFT.md` — the agent's operating manual (in small scope, test before declaring done, never flip status itself, set `blocked` + a question in the log if stuck)

**Done when:** `./night-shift/run.py` takes an approved order and produces a branch with working code plus a review-ready log — with zero human interaction.

### Phase 2 — The day shift decides  *make the loop a habit*

- [ ] `day-shift/status.py` — factory floor report: queued orders, orders in review, branches awaiting merge
- [ ] Decision conventions: a human reviews `wo/NNN`, then either
  - merges the branch and marks `done`, or
  - sets `blocked` with a question for tonight, or
  - sets `rejected` with a reason
- [ ] Squash-merge convention: the night agent must never merge; only day shift merges

**Done when:** a full day/night cycle has run with real work: order → overnight implementation → morning review → merged.

### Phase 3 — Hardening  *once the loop is trusted*

- [ ] **Isolation**: run each order in a `git worktree` so night runs can't collide or touch the main checkout
- [ ] **Auditability**: switch to `pi --mode json` and archive full event streams in `night-shift/logs/`, not just final text
- [ ] **Validation**: `night-shift/lint-order.py` — reject malformed orders (missing id/status/tasks) before spending tokens
- [ ] **Scheduling**: cron/systemd timer (or `at`) so the night shift literally starts itself; wake word: nothing — it just runs
- [ ] **Budget rails**: per-order token/time cap; abort and mark `blocked` when exceeded

### Phase 4 — Expansion  *only if the loop proves out*

- [ ] **QA pre-shift**: a second pi pass that reviews the night's diff and writes a review packet, so the morning human-review takes minutes
- [ ] **Skills** for recurring job types ("add a CLI command", "write a migration") loaded via `pi --skill`
- [ ] **Prompt templates** for authoring work orders consistently
- [x] **Multi-repo** — pulled forward into Phase 1: orders name a target repo
  (`repo:` path or git URL, cloned under `repos/`); one factory process per
  repo, lock-guarded; day shift merges and pushes target repos themselves.
- [ ] **Parallel shifts**: multiple isolated worktrees running different orders concurrently

## Scope discipline (what "minimal" means)

In scope for now: **Phases 0–2 only.** Plain Python (stdlib) + markdown.
Hosts: pi and Claude Code (engine per run), both under the nWave guard.
Orders may target external repos; one factory process per repo. One order per night run by default.

Explicitly out of scope until Phase 3+: worktrees, JSON event archives, cron, budgets, multi-repo, parallelism. Every phase must leave the factory usable on its own — no half-built scaffolding.

## Risks & guardrails (baked in from Phase 1)

| Risk | Guardrail |
|---|---|
| Agent merges its own work | Merging is a day-shift-only convention; night runner never merges |
| Agent runs away on a vague order | Night manual: if acceptance criteria are unclear → set `blocked`, ask a question, stop |
| Secrets/credentials exposed to the agent | Orders reference files, never inline secrets; `.env`-style files gitignored from day one |
| Night run corrupts the repo | Each order works on its own branch; `main` only moves via day-shift merges |
| Silent failures | Runner logs every attempt (success or not) to `night-shift/logs/` and never deletes logs |
