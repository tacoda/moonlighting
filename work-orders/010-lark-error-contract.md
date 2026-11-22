---
id: 010
title: Errors are data — a documented CLI error contract
status: approved
created: 2026-11-22
branch: wo/010
repo: /home/linuxuser/repos/lark
---

## Goal

Design principle 4 says "errors are data — failures surface as structured
values, never as opaque strings". At the CLI boundary that promise needs a
contract: agents calling `lark run` and `lark -e` must be able to tell error
classes apart by exit code and parse the stderr. Define it, test it, and
document it in SPEC.md.

## Tasks

- Inventory the error classes that reach the CLI: reader/parse errors, eval
  errors, file-not-found, and success.
- Define the contract: a distinct exit code per class (e.g. 0 success,
  1 usage, 2 parse, 3 eval, 4 file-not-found — pick and document the final
  table), and a stable one-line stderr prefix per class
  (e.g. `parse error: ...`, `eval error: ...`).
- Add golden tests under `testdata/` following the existing golden pattern:
  one input file per error class, asserting stderr and exit code.
- Document the table in `docs/SPEC.md`.

## Constraints

- No language or evaluator semantics changes — this is the CLI layer,
  testdata, and SPEC only.
- Follow the repo's existing golden-test pattern (`testdata/`, `.out`
  files).
- `go vet ./...` and `go test ./...` must pass.

## Acceptance criteria

- A golden test per error class asserts exit code and stderr format.
- SPEC.md contains the exit-code/error-format table matching the tests.
- The report includes the final contract table and one real invocation per
  class.

## Night shift log

(runner appends reports here)

## Day shift decisions

(humans decide here)
