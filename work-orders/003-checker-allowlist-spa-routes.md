---
id: 003
title: Checker allowlist for SPA routes
status: draft
created: 2026-11-22
branch: wo/003
repo: /home/linuxuser/repos/tacoda.github.io
---

## Goal

`tools/check-links.py` can distinguish "broken" from "works via the SPA
404-bounce", so its exit code tells the truth: everything it flags is a real
dead end. The three client-side routes stay; the dead project pages stay
flagged until the day shift decides their fate.

## Tasks

- Add a repeatable `--allow <path>` flag to `tools/check-links.py`: allowed
  targets are reported in a separate "allowed (SPA routes)" section but do
  not affect the exit code.
- Update the run convention (a short usage note in the script's docstring is
  enough): `python3 tools/check-links.py --allow /resources --allow /about
  --allow /projects`.
- Do NOT touch any HTML, JS, or essay links. In particular: the homepage
  project cards and the links to `/ghola/`, `/gauge/`, `/keystone/`,
  `/open-refinery/` stay exactly as they are — the day shift has not decided
  their fate (create / repoint / remove).

## Constraints

- Plain Python 3 stdlib, single file, still no dependencies.
- Only `tools/check-links.py` may change.
- Exit semantics: exit 0 only when no broken (non-allowed) internal links
  remain; exit 1 otherwise, with the per-page list.

## Acceptance criteria

- With the three `--allow` flags, the output's only remaining broken targets
  are `/ghola/`, `/gauge/`, `/keystone/`, `/open-refinery/` — enumerated with
  referring-page counts — and the exit code is 1 (they are genuinely dead).
- Without flags, output and exit code are unchanged from today (exit 1, all
  7 targets listed).
- Diff touches `tools/check-links.py` only.

## Night shift log

(runner appends reports here)

## Day shift decisions

(humans decide here)
