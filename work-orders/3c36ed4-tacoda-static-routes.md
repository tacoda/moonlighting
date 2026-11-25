---
id: 3c36ed4
title: Static pages for the SPA deep-link routes
status: blocked
created: 2026-11-22
branch: wo/3c36ed4
repo: /home/linuxuser/repos/tacoda.github.io
---

## Goal

`/about`, `/projects` and `/resources` render client-side only: crawlers and
link previews get an HTTP 404 before the SPA bounces. Give each route a real
static `index.html` so deep links return 200 with meaningful content, while
the SPA keeps working unchanged.

## Tasks

- Read root `index.html` to find what each route renders (the SPA's views
  and their data), then create `about/index.html`, `projects/index.html`,
  `resources/index.html` — static pages carrying that same content: the
  essays/resources list, the project list, and the about text.
- Keep the visual treatment consistent with the essay pages (same head,
  styles, and a link back to `/`).
- Update the docstring run-convention in `tools/check-links.py`: once these
  exist, the three SPA-route `--allow` entries are no longer needed (the
  targets resolve); `/ghola/`-style sibling pages remain allowlist-only.

## Constraints

- No changes to root `index.html`'s JavaScript or to any essay page.
- Only new files (`about/`, `projects/`, `resources/`, each with
  `index.html`) plus the `tools/check-links.py` docstring.
- Content must come from what the SPA already renders — no new copy, no
  invented projects.

## Acceptance criteria

- The three files exist and link back to `/`; each carries the content its
  SPA route renders (project names, essay/resource links).
- `tools/check-links.py --allow /ghola/ --allow /gauge/ --allow /keystone/
  --allow /open-refinery/` exits 0, and the three former SPA routes now
  resolve without allows (they surface as unused-allow notes, which is
  expected).
- `git diff main --stat` shows only the new directories and the checker
  docstring.

## Night shift log

(runner appends reports here)

## Day shift decisions

(humans decide here)

### 2026-11-25 — blocked by day shift. Target repos live on the old server. Re-point to this machine, then re-approve.
