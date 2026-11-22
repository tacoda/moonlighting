---
id: 007
title: Atom feed for the essays
status: approved
created: 2026-11-22
branch: wo/007
repo: /home/linuxuser/repos/tacoda.github.io
---

## Goal

The site has ~38 essays and no feed. Readers (and agents) should be able to
subscribe: an Atom feed at `/feed.xml`, regenerated whenever an essay lands.

## Tasks

- Write `tools/gen-feed.py` (Python 3 stdlib, re-runnable): walks the essay
  directories, builds an Atom 1.0 `feed.xml` — one entry per essay with
  title (from `<title>`), updated date (latest commit date touching that
  directory, from `git log`), and a link to the essay URL.
- Run it and commit `feed.xml`.
- Add `<link rel="alternate" type="application/atom+xml" href="/feed.xml">`
  to root `index.html`.
- Use the canonical domain from the `CNAME` file for all URLs.

## Constraints

- Python stdlib only; the generator is committed so the feed can be
  regenerated (`python3 tools/gen-feed.py`).
- No essay content changes; the only HTML change is the feed `<link>` in
  root `index.html`.
- `tools/check-links.py` must stay green with the existing run convention.

## Acceptance criteria

- `feed.xml` parses as well-formed XML (e.g. `python3 -c
  "import xml.etree.ElementTree as ET; ET.parse('feed.xml')"`) and is valid
  Atom 1.0 (feed/entry/title/link/updated elements).
- One entry per essay directory; dates are ISO and match `git log`.
- `tools/check-links.py` (with the sibling/SPA allowlist) still exits 0.

## Night shift log

(runner appends reports here)

## Day shift decisions

(humans decide here)
