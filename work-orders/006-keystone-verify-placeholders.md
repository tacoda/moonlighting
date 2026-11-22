---
id: 006
title: verify flags placeholder checks that silently pass
status: approved
created: 2026-11-22
branch: wo/006
repo: /home/linuxuser/repos/keystone
---

## Goal

`keystone verify` should refuse to bless a charter full of scaffolding: the
`new pattern` / `new guide` / `new document` templates ship with placeholder
checks (`run: "true"` — a check that always passes) and TODO descriptions,
and today verify says nothing. A charter framework's own tooling should
catch a do-nothing check.

## Tasks

- In `keystone verify`, detect placeholder checks: a check whose `run` value
  is exactly `"true"`, or whose description still contains a `TODO` marker.
- Print a warning per finding, naming the file and the field
  (e.g. `warning: patterns/my-check.md — run is placeholder "true"`).
- Warnings only: the exit code and all existing verdicts are unchanged.
- Add fixture-based tests: a charter with placeholders produces the warnings;
  a charter with real checks produces none.

## Constraints

- Go stdlib only; `go vet` and `go test ./...` must pass.
- Warnings are non-breaking — do not change verify's exit semantics.
- Off-limits (uncommitted human work): `README.md`, `docs/plans/**`,
  `internal/framework/primitive/**`, `internal/framework/projection/**`.

## Acceptance criteria

- Fixture with a `run: "true"` check → verify prints a warning naming it.
- Fixture with real checks → no warnings.
- `go test ./...` green, `go vet` clean.
- The report includes the exact warning output for both fixtures.

## Night shift log

(runner appends reports here)

## Day shift decisions

(humans decide here)
