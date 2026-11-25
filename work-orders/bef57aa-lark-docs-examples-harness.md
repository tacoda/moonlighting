---
id: bef57aa
title: Every documented lark example runs — a docs verification harness
status: blocked
created: 2026-11-22
branch: wo/bef57aa
repo: /home/linuxuser/repos/lark
---

## Goal

Lark's promise is "what you write is what runs" — its documentation should
keep that promise too. Build a test harness that extracts every code example
from `README.md` and `docs/SPEC.md`, runs it through the lark CLI, and fails
when an example errors or disagrees with its stated output. Fix the docs
that fail.

## Tasks

- Add a Go test (e.g. `internal/docs_examples_test.go`) that:
  - extracts fenced code blocks tagged `lark`/`scheme` from `README.md` and
    `docs/SPEC.md`;
  - executes each via the CLI entrypoint (`go run ./cmd/lark -e ...` or the
    package API — whichever is cleaner);
  - compares against stated output (REPL-style `=> result` lines) where the
    doc states one; otherwise asserts only that evaluation succeeds.
- Run it. Fix every failing example by correcting the documentation (the
  language is v0-complete and tested — trust the tests, not the docs).
- Non-code blocks (prose, shell) are skipped.

## Constraints

- No changes to the language, evaluator, or CLI behavior — docs and the new
  test only.
- `go vet ./...` and `go test ./...` must pass.

## Acceptance criteria

- The harness reports the total number of examples verified.
- `go test ./...` green, including the new harness.
- The report lists each doc file's example count and any corrections made.

## Night shift log

(runner appends reports here)

## Day shift decisions

(humans decide here)

### 2026-11-25 — blocked by day shift. Target repos live on the old server. Re-point to this machine, then re-approve.
