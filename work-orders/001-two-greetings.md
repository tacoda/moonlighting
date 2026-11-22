---
id: 001
title: Two greetings, so the day can pick
status: done
created: 2026-11-22
branch: wo/001
---

## Goal

Give the day shift two working variants of a greeting command to choose
between. Both must work; the choice happens in the morning, not at 2am.

## Tasks

- Create `bin/greet-formal`: prints `Good evening. The factory is operational.`
- Create `bin/greet-casual`: prints `yo — night shift, reporting for duty.`
- Make both executable (`chmod +x`).

## Constraints

- Plain bash only — no frameworks, no argument parsing, no config files.
- Create nothing else: no README edits, no tests scaffolding, no extra files.

## Acceptance criteria

- `./bin/greet-formal` exits 0 and prints exactly `Good evening. The factory is operational.`
- `./bin/greet-casual` exits 0 and prints exactly `yo — night shift, reporting for duty.`
- The report states which variant you would ship by default, and why, in one sentence.

## Night shift log

(runner appends reports here)

## Day shift decisions

(humans decide here)

### 2026-11-22 04:28 — night run (engine pi, target this factory), exit 0 (29s)

Committed on `wo/001`, clean tree, order file untouched.

---

## Report — Work order 001

**1. Status: DONE**

**2. What I did**
Created the two greeting variants as plain bash scripts in `bin/`, made both executable, and committed on `wo/001`. Nothing else was touched — no README edits, no tests, no extra files, no changes to the order file.

**3. Files changed**
- `bin/greet-formal` (new, mode 100755) — prints `Good evening. The factory is operational.`
- `bin/greet-casual` (new, mode 100755) — prints `yo — night shift, reporting for duty.`

**4. How I verified**
- `./bin/greet-formal` → exit 0, output byte-compared equal to `Good evening. The factory is operational.` — **PASS**
- `./bin/greet-casual` → exit 0, output byte-compared equal to `yo — night shift, reporting for duty.` (`od -c` confirms proper UTF-8 em dash, `342 200 224`) — **PASS**
- `git status` shows only `bin/` added; both files committed with mode `100755` — **PASS** (executable bit preserved in git)
- Constraints check: both are 2-line `#!/usr/bin/env bash` + `echo` scripts, no args parsing, no config — **PASS**

**5. Recommendation (required by acceptance criteria)**
Ship `greet-formal` by default — the em dash in `greet-casual` is non-ASCII and can garble on terminals with mismatched locale settings, so the formal variant is the safer default everywhere.
