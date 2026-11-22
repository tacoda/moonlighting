---
id: 004
title: Keep the formal greeting, remove greet-casual
status: review
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

### 2026-11-22 05:33 — night run (engine pi, target this factory), exit 0 (26s)

All acceptance criteria verified. Final report:

---

## Status

**DONE**

## What I did

Deleted `bin/greet-casual` via `git rm` and committed it on `wo/004`, closing out wo-001's accepted recommendation. Nothing else was touched — `bin/greet-formal` is byte-identical (sha256 unchanged before and after).

## Files changed

- `bin/greet-casual` — deleted (commit `363f5fe`)

## How I verified

| Acceptance criterion | Command | Result |
|---|---|---|
| `greet-formal` exits 0, exact output | `./bin/greet-formal` compared string-equal to `Good evening. The factory is operational.`, exit code 0 | PASS |
| `greet-formal` byte-identical | `sha256sum bin/greet-formal` before and after | Unchanged: `5f8771ed…a3be9` |
| `greet-casual` gone | `ls bin/` + existence check | Only `greet-formal` remains |
| `git diff main` shows only that deletion | `git diff main --name-status` | Single line: `D bin/greet-casual` |

Working tree is clean; branch `wo/004` has exactly one commit ahead of `main`. No order files, README, or anything outside `bin/` modified.

## Questions / follow-ups

None.
