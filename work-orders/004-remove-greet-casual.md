---
id: 004
title: Keep the formal greeting, remove greet-casual
status: draft
created: 2026-11-22
branch: wo/004
---

## Goal

Close out wo-001's decision: the day shift keeps `bin/greet-formal` as the
factory's greeting and discards the casual variant (night-shift
recommendation, accepted during review).

## Tasks

- Delete `bin/greet-casual`.
- Nothing else. `bin/greet-formal` stays byte-identical.

## Constraints

- Do not touch the order files, README, or anything outside `bin/`.

## Acceptance criteria

- `./bin/greet-formal` still exits 0 and prints exactly
  `Good evening. The factory is operational.`
- `bin/greet-casual` no longer exists; `git diff main` shows only that
  deletion.

## Night shift log

(runner appends reports here)

## Day shift decisions

(humans decide here)
