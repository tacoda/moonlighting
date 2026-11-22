---
id: 005
title: Catch CHANGELOG up to shipped work
status: approved
created: 2026-11-22
branch: wo/005
repo: /home/linuxuser/repos/keystone
---

## Goal

CHANGELOG.md stops at 5.0.2 (2026-11-06) while several features have shipped
since (relocation, charter query, movers, starter pack removal). Bring it
current so the project's own history is readable again.

## Tasks

- Inventory every commit since the 5.0.2 release commit (`git log`).
- Add an `## [Unreleased]` section grouped Added / Changed / Fixed / Removed
  per Keep a Changelog, in the file's existing voice and format.
- Skip pure-chore commits; merge trivial commit series into one entry where
  the changelog reads better that way.

## Constraints

- Only CHANGELOG.md may change.
- No version bump, no release date — the `[Unreleased]` section stays
  unreleased; cutting a release is the human's call.
- These paths have uncommitted human work and are off-limits: `README.md`,
  `docs/plans/**`, `internal/framework/primitive/**`,
  `internal/framework/projection/**`.

## Acceptance criteria

- Every non-chore commit since 5.0.2 is represented by at least one entry.
- Entries reference real commands/features (spot-check: relocation and
  charter query both appear).
- The report includes the commit→entry mapping.

## Night shift log

(runner appends reports here)

## Day shift decisions

(humans decide here)
