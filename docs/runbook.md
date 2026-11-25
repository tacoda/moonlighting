# Runbook — moonlighting factory

## First-time setup (once)

1. Install pi: `curl -fsSL https://pi.dev/install.sh | sh` (and/or the Claude
   Code CLI, if you want the `claude` engine).
2. Log the host(s) in: `pi` → `/login`; `claude` login on first run.
3. Put both hosts under the nWave guard — install once, then activate
   globally (revert with `nwave-ai mode opt-in`):

       nwave-ai install --platform pi
       nwave-ai install --platform claude-code
       nwave-ai install --platform opencode
       nwave-ai mode all

4. Make an initial commit: the night runner needs a clean tree on `main` with
   at least one commit.
5. Smoke-test: `python3 night-shift/run.py --dry-run`
6. When you trust the loop, let nights start themselves:
   `python3 night-shift/schedule.py install [--engine pi|claude|opencode]`
   (fires nightly, harmlessly no-ops on an empty queue, `remove` undoes it,
   `status` shows the entry).

> The runner invokes pi with `--approve`, which trusts project-local
> configuration so the night can run unattended. Only run the night shift in
> repos you control.

## Writing orders (day shift)

- `cp docs/work-order-template.md work-orders/00N-short-title.md` — zero-pad
  ids to 3 digits; one order = one branch = one review. Ids are never reused,
  even after `done`.
- Before approving: `python3 night-shift/lint-order.py` — it catches
  malformed orders (missing fields, empty sections, bad repo paths) before
  they spend tokens. The night runner also lint-blocks approved orders
  automatically.
- Target another repo with the `repo:` frontmatter field: a path
  (`repo: ~/repos/shop`) or a git URL (`repo: https://github.com/acme/api.git`,
  cloned under `repos/` and refreshed each night). Omit it to target this
  factory itself.
- Pick the model per order with a `model:` frontmatter field. The string
  passes verbatim to the selected engine (syntax per host: see the README
  engines table). Leave it out for the host default.
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

1. Factory floor clean (commit or stash — bookkeeping commits land there).
   Target repos don't need to be clean anymore: nights run in throwaway
   worktrees (`night-shift/worktrees/`, removed after each run) and never
   touch your working copies.
2. `python3 night-shift/run.py --dry-run [--repo R]` — preview tonight's queue.
3. One factory process per repo; separate factory clones run in parallel:

       python3 night-shift/run.py --repo ~/repos/shop
       python3 night-shift/run.py --repo git@github.com:acme/api.git --engine claude

   `--repo` takes a path or URL and only runs that repo's orders; the default
   works this factory's own queue. Pick the host with `--engine
   pi|claude|opencode` and the model with `--model` (host-specific syntax).
4. `--max-orders N` for a longer night; an order that runs past
   `NIGHT_TIMEOUT_SECS` (default 7200s) is killed and marked blocked.
5. Locks: a second process on the same repo or the same factory checkout
   refuses to start instead of racing you. A lock left by a dead process is
   broken automatically.

## Morning checklist (day shift)

1. `python3 day-shift/status.py` (all repos; filter with `--repo`)
2. For each `review` order:
   - Read the **QA pre-shift verdict** (SHIP/BLOCK/UNSURE) and the agent's
     report in the order file — the QA packet's criteria table is your
     shortcut; spot-check what it flags.
   - Review the branch **in its target repo**:
     `git -C <target> diff main...wo/NNN` — run the result if warranted.
   - Good → `python3 day-shift/accept.py NNN` (squash-merges into the target's
     main, marks done). Push the target repo yourself — the factory never
     pushes.
   - Not there yet → set `blocked`, append your question under
     *Day shift decisions*; tonight's rerun continues the same agent session,
     so it remembers its own work.
   - Wrong direction → `rejected`, with a reason.
3. For each `blocked`: answer the agent's question in the order file, flip to
   `approved`.
4. Write tonight's orders, approve them, go home.

## Forensics

- Order file — every run's report plus the QA pre-shift verdict.
- Raw agent output — `night-shift/logs/YYYY-MM-DD-wo-NNN.out.md` (+
  `.err.log` on failures).
- Night never started? `night-shift/logs/errors.log` holds pre-flight
  failures: dirty floor, wrong branch, missing binary.
- Full event streams — `night-shift/logs/*.events.jsonl` and `*.qa.jsonl`:
  every tool call, every token, archived. This is the factory's flight
  recorder.
- Sessions — pi: `pi --session wo-NNN`. claude: `claude --resume <uuid>`.
  opencode: the id (`ses_...`) from `night-shift/sessions.json`.
- Worktrees — created per run under `night-shift/worktrees/`, removed when
  the run ends. To poke at a finished night: `git -C <target> diff
  main...wo/NNN`, or `git -C <target> worktree add /tmp/poke wo/NNN`.

## Conventions

- `main` moves by day-shift squash-merges only — plus night bookkeeping
  commits (status flips, logs), which never contain code. Same for every
  target repo's main.
- Agents never edit `work-orders/`; the runner appends reports and flips
  statuses.
- Logs are append-only. They are the factory's memory; never delete them.
- Change the factory scripts? Run the suite: `uv run pytest`.

## Night-branch base policy

Night branches start from the target's **local main, fast-forwarded to the
remote default when possible**. The fast-forward runs only when the target
has main checked out, so any other checkout stays untouched. Consequence:
after accepting an order, push
the target repo (or at least approve the next order only after the previous
landing is integrated) — the night wants your freshest main.
