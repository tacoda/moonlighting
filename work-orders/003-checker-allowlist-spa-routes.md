---
id: 003
title: Checker allowlist for SPA routes and sibling project pages
status: approved
created: 2026-11-22
branch: wo/003
repo: /home/linuxuser/repos/tacoda.github.io
---

## Goal

`tools/check-links.py` can model the whole site namespace — this repo, the
SPA's client-side routes, and sibling GitHub Pages project sites — so its
exit code tells the truth: exit 0 means every internal link is accounted
for, not that the internet was scanned.

## Day shift decisions (recorded 2026-11-22)

- `/resources`, `/about`, `/projects` are SPA client-side routes. They work
  in production via the `404.html` bounce. Keep them; the checker learns to
  allow them explicitly.
- `/ghola/`, `/gauge/`, `/keystone/`, `/open-refinery/` (and `/sigma/`,
  `/caml/`, `/otto/`, `/reins/` advertised in homepage JS) are **separate
  GitHub project pages** — sibling repos publishing under
  `tacoda.github.io/<repo>/`. They are not dead links; they live outside
  this repo's tree, which is the only reason the checker flagged them.
- No HTML, JS, or essay links may be changed by this order.

## Tasks

- Add a repeatable `--allow <path>` flag to `tools/check-links.py`: allowed
  targets are listed in a separate "allowed" section of the output and do
  not affect the exit code.
- Update the script's docstring with the run convention and the two allowed
  classes:
  - SPA routes: `--allow /resources --allow /about --allow /projects`
  - sibling project pages: `--allow /ghola/ --allow /gauge/ --allow
    /keystone/ --allow /open-refinery/`
- Do NOT touch any HTML, JS, or essay links.

## Constraints

- Plain Python 3 stdlib, single file, still no dependencies.
- Only `tools/check-links.py` may change.
- Exit semantics: exit 0 when every internal link is either resolved or
  explicitly allowed; exit 1 otherwise, with the per-page list.

## Acceptance criteria

- With all seven `--allow` paths, the checker exits 0 and its output lists
  the allowed targets separately from resolved ones.
- Without flags, behavior is unchanged from today: exit 1, all 7 targets
  listed with referring-page counts.
- Diff touches `tools/check-links.py` only.

## Night shift log

(runner appends reports here)

## Day shift decisions

(humans decide here)

### 2026-11-22 05:20 — night run (engine pi, target /home/linuxuser/repos/tacoda.github.io), exit 0 (0s)

**Status** — BLOCKED (by the runner, before the agent started)

target repo has uncommitted changes — the factory will not mix your WIP into a night branch

### 2026-11-22 (day shift) — blocked-run answer

Block cause: accept.py had left wo-002's squash-merge staged-but-uncommitted
in the target repo; the dirty-tree guardrail correctly refused to start.
Bug fixed (accept.py now commits in the target repo); wo-002 landing
completed. Re-approved for tonight.
