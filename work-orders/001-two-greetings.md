---
id: 001
title: Two greetings, so the day can pick
status: approved
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
