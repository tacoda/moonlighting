---
id: 002
title: Link audit and repair for tacoda.github.io
status: approved
created: 2026-11-22
branch: wo/002
repo: /home/linuxuser/repos/tacoda.github.io
---

## Goal

Every internal link on the site resolves to a real page. Deliver a
re-runnable link checker plus the safe repairs; anything ambiguous becomes a
question for the day shift, never a guess.

## Tasks

- Build `tools/check-links.py`: scan every `index.html` (all essay
  directories, plus root `index.html` and `404.html`), extract `href` and
  `src` targets, and resolve each against the **repo root** — this site
  deploys at its domain root, so `/factory/` means `<repo>/factory/index.html`
  or `<repo>/factory/`. Skip external (`http(s)`, `mailto:`), fragment-only
  (`#...`), and JavaScript template text like `${p.href}`.
- Run it and repair what is genuinely fixable: a typo'd slug, a link to a
  renamed directory, a wrong extension.
- For targets that don't exist and shouldn't be invented (scout pass
  suspects: `/resources`, `/about`, `/projects`, `/ghola/`, `/gauge/`,
  `/keystone/`, `/open-refinery/`): do NOT create pages or point links
  elsewhere. List each in the report with the count of referring pages and a
  one-line recommendation per target (create it / remove the links / point
  at an existing page — which one).

## Constraints

- Checker: plain Python 3 stdlib, single file, no dependencies.
- Only repairs to `href`/`src` attribute values plus the new `tools/` file.
  No prose edits, no reformatting, no redesign, no new pages.
- The target repo works on its `main` branch conventions — read its README
  before committing there.

## Acceptance criteria

- `python3 tools/check-links.py` runs, exits 0 when no broken internal links
  remain, exits 1 with a per-page list otherwise.
- Every repair changes only a `href`/`src` value (verifiable in the diff).
- The report enumerates all remaining broken targets with referring-page
  counts and a recommendation each.

## Night shift log

(runner appends reports here)

## Day shift decisions

(humans decide here)
