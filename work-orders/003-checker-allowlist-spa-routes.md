---
id: 003
title: Checker allowlist for SPA routes and sibling project pages
status: done
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

### 2026-11-22 05:25 — night run (engine pi, target /home/linuxuser/repos/tacoda.github.io), exit 0 (232s)

1. **Status** — DONE

2. **What I did** — Extended `tools/check-links.py` with a repeatable `--allow <path>` flag. Allowed targets are matched **exactly** against resolved link URLs, reported in a separate "Allowed internal links" section with per-target ref/page counts, and never affect the exit code. Allow entries that match zero links are printed as `0 refs (allowed but never referenced)` so flag typos can't hide behind exit 0. The docstring now records the run convention and both allowed classes (SPA routes via 404.html bounce; sibling repos published under `tacoda.github.io/<repo>/`).

   One base correction, flagged for the runner: `wo/003` was cut from `origin/main` (a5a1946), which is stale — the wo-002 checker lives only on local `main` (6d19ca3, never pushed). Since the order builds on that checker ("behavior is unchanged from today"), I fast-forwarded `wo/003` (which had no commits of its own) to local `main` before starting. No merge, no push, `main` untouched.

3. **Files changed** — `tools/check-links.py` only (+88/−41; commit `3a809cb` on `wo/003`, based on `main`@`6d19ca3`). No HTML, JS, or essay files touched.

4. **How I verified** (all acceptance criteria):
   - **Seven `--allow` paths → exit 0**, allowed targets listed separately: "OK: 38 pages scanned, no broken internal links." + "Allowed internal links: 51 occurrences of 7 targets across 37 pages" — counts mirror today's broken counts exactly.
   - **No flags → behavior unchanged**: byte-for-byte identical output vs. the pre-change script (diffed against a stashed baseline), exit 1, all 7 targets with referring-page counts.
   - Edge cases: partial flags leave the rest broken with exit 1; `--allow /ghola` (no slash) does *not* permit `/ghola/` (exact match, as documented); unused allows surfaced; `--help` works.
   - `git diff --stat main` touches only `tools/check-links.py`; imports all stdlib (`argparse`, `html`, `pathlib`, `re`, `sys`, `urllib`); compiles clean; tree clean after commit.

5. **Questions / follow-ups**
   - **Runner bug (likely same class as the wo-003 pre-block):** night branches are cut from `origin/main`, but accepted work lands on local `main` and is never pushed — so every night branch after an accepted order starts one landing behind. Tonight it was recoverable with a fast-forward because wo/003 had no own commits; once branches carry work, this will need a rebase or a fixed runner. Worth a look before the next order.
   - Homepage JS advertises `/sigma/`, `/caml/`, `/otto/`, `/reins/` per the day-shift note, but today's scan finds no such links in any parsed attribute (the JS builds them from data, and `${...}`/external values are skipped by design) — they're documented in the docstring but not needed in the run convention today.
