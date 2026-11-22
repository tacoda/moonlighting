# Runbook — moonlighting factory

## First-time setup (once)

1. Install pi: `curl -fsSL https://pi.dev/install.sh | sh`
2. Run `pi` in this repo → `/login` → approve the project-trust prompt.
3. Make an initial commit: the night runner needs a clean tree on `main` with
   at least one commit.
4. Smoke-test: `python3 night-shift/run.py --dry-run`

> The runner invokes pi with `--approve`, which trusts project-local
> configuration so the night can run unattended. Only run the night shift in
> repos you control.

## Writing orders (day shift)

- `cp docs/work-order-template.md work-orders/00N-short-title.md` — zero-pad
  ids to 3 digits; one order = one branch = one review.
- An order should be decidable in one morning. Big unknown? Order prototypes
  or variants and decide among them in the morning — the night produces
  options, the day produces answers.
- Acceptance criteria are what the agent tests against — make them runnable
  ("`./bin/greet` exits 0 and prints X", not "make it nice").
- `Constraints` is where you say what NOT to touch. The night manual already
  forbids drive-by refactors; add what's specific to this order.
- Approving = handing over. Read the order once more as if you had to do the
  work yourself with no one to ask — because at 2am, that's exactly true.

## Kicking off the night (day shift, before leaving)

1. Floor clean? Commit or stash — night runs refuse a dirty tree.
2. `python3 night-shift/run.py --dry-run` — preview tonight's queue.
3. `python3 night-shift/run.py` (one order) or `--max-orders N` for a longer night.
4. An order that runs past `NIGHT_TIMEOUT_SECS` (default 7200s) is killed and
   marked blocked.

## Morning checklist (day shift)

1. `python3 day-shift/status.py`
2. For each `review` order:
   - Read the agent's report in the order file (status / what / verified /
     follow-ups).
   - `git diff main...wo/NNN` — run the result yourself if warranted.
   - Good → `python3 day-shift/accept.py NNN` (squash-merges into main,
     marks done).
   - Not there yet → set `blocked`, append your question under
     *Day shift decisions*; tonight's rerun continues the same pi session,
     so the agent remembers its own work.
   - Wrong direction → `rejected`, with a reason.
3. For each `blocked`: answer the agent's question in the order file, flip to
   `approved`.
4. Write tonight's orders, approve them, go home.

## Forensics

- Order file — every run's report, oldest first.
- Raw pi output — `night-shift/logs/YYYY-MM-DD-wo-NNN.out.md` (+ `.err.log`
  on failures).
- Full conversation — `pi --session wo-NNN` reopens the exact night session
  interactively.

## Conventions

- `main` moves by day-shift squash-merges only — plus night bookkeeping
  commits (status flips, logs), which never contain code.
- Agents never edit `work-orders/`; the runner appends reports and flips
  statuses.
- Logs are append-only. They are the factory's memory; never delete them.
