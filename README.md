# moonlighting

A software factory where **people work the day shift and agents work the night
shift**. People decide. Agents type. The workforce is the engine you select
for the run: pi, Claude Code or opencode.

## How it works

Work moves through the factory as **work orders** — small markdown files in
`work-orders/` whose `status:` line is the contract between the shifts.
Marking an order `approved` is a standing instruction: tonight, an agent
executes it autonomously. In the morning it sits at `review` — with a report,
a branch, and a diff, waiting for a human decision.

```
day shift (people)                     night shift (selected engine)
decide what problems matter  ──────►   implement approved orders
review branches & reports    ◄──────   flip orders to review/blocked
merge, block, or reject               never merge, never touch main
```

The night runs on one command:

```bash
./night-shift/run.py              # execute the oldest approved order
```

and the morning starts with another:

```bash
./day-shift/status.py             # what needs my decision?
```

## Layout

```
work-orders/            order files (input, gitignored; FACTORY_ORDERS_DIR relocates it)
night-shift/run.py      the night runner (headless pi, claude or opencode)
night-shift/NIGHT-SHIFT.md   the night agent's operating manual
night-shift/QA-SHIFT.md      the QA pre-shift reviewer's manual
night-shift/lint-order.py    validate work orders before spending tokens
night-shift/schedule.py      install/remove the nightly cron entry
night-shift/logs/       run reports, QA packets, event streams, morning digest (append-only)
night-shift/sessions.json   engine session ids per order (local state, gitignored)
night-shift/locks/      run locks (gitignored)
night-shift/worktrees/  per-run worktrees of target repos (gitignored, removed after each run)
repos/                  target repos cloned from git URLs (gitignored)
day-shift/status.py     factory floor report
day-shift/new-order.py  create the next order from the template
day-shift/accept.py     squash-merge a reviewed order into its target repo
day-shift/rotate-logs.py    gzip old night logs into logs/archive/ (never deletes)
factory.py              shared helpers for the factory scripts
docs/work-order-template.md  how orders are written
docs/runbook.md         shift checklists (morning, handover, forensics)
docs/flow.md            mermaid diagrams: the day/night work flow
PLAN.md                 phased roadmap
tests/                  pytest suite for the factory scripts
pyproject.toml          uv project (dev dependency: pytest), with uv.lock
AGENTS.md               standing instructions for any agent in this repo
```

## The rules

- The night shift executes only `approved` orders, each on its own branch (`wo/NNN`).
- Only the day shift merges code into `main` (squash, via `day-shift/accept.py`).
  Night bookkeeping (run logs) commits straight to `main` — but never contains code.
  The factory treats order files as input: gitignored, relocatable via
  `FACTORY_ORDERS_DIR`.
- A blocked or ambiguous order stops the agent. It asks; it never guesses.
- The night shift produces **options, not answers**: when the problem is
  unknown, an order asks for variants, and the day shift decides among them.
- Orders can target other repos: `repo:` frontmatter takes a path or a git
  URL (URLs are cloned under `repos/` and refreshed each night). Night work
  happens in a throwaway git worktree of the target repo — your working
  copies are never switched or touched; only the day shift merges there, and
  the factory never pushes.

## Engines

Three hosts run the same work orders through the same flow:

| engine | headless invocation | sessions | model syntax |
| --- | --- | --- | --- |
| pi (default) | `pi --print` | deterministic: `wo-NNN` | `provider/id`, optional `:thinking` |
| claude | `claude -p` | uuid per order, kept in `night-shift/sessions.json` | alias or full model id |
| opencode | `opencode run` | host picks the id (`ses_...`), kept in `night-shift/sessions.json` | `provider/model#variant` |

Pick per run with `--engine` (or `FACTORY_ENGINE`). All three run under the
nWave tool-call guard (`nwave-ai mode all`). Agent commits carry nWave
attribution.

Set the model in three places, most specific first: a `model:` field,
`--model` (or `FACTORY_MODEL`), or the host default. The string passes
verbatim to the selected engine. Write it in that engine's syntax from the
table. Each run header records the model that ran.

The QA pass can run its own model. Use `--qa-model` (or env
`FACTORY_QA_MODEL`). Without it, QA uses the order model.

Every run is double-checked by default:

- **JSON audit** — the engine's full event stream is archived to
  `night-shift/logs/*.events.jsonl`; the final report is extracted from it.
  Opt out with `FACTORY_JSON_AUDIT=0`.
- **QA pre-shift** — a second agent pass reviews the night's diff against the
  acceptance criteria and writes a verdict (SHIP/BLOCK/UNSURE) into the order
  file, so the morning decision takes minutes. Opt out with `FACTORY_QA=0`.

## Several factories, several repos

One factory process per target repo; processes run in parallel:

```bash
python3 night-shift/run.py --repo ~/repos/shop
python3 night-shift/run.py --repo git@github.com:acme/api.git --engine claude
```

Locks make collisions visible: one night per target repo, one night per
factory checkout. For true parallel nights, clone this factory once per repo
and run one process in each:

```bash
git clone ~/repos/moonlighting ~/factories/shop-factory
cd ~/factories/shop-factory
python3 night-shift/run.py --repo ~/repos/shop
# in another terminal, another clone, another repo, same time — no conflict
```

The morning is still one command per factory:

```bash
python3 day-shift/status.py
```

## Requirements

- git and Python 3.9+ (the runtime needs only the standard library)
- for development: [uv](https://docs.astral.sh/uv/) — `uv sync` installs
  pytest, `uv run pytest` runs the suite
- the host CLI for your selected engine, logged in. Pick [pi](https://pi.dev)
  (`pi` → `/login` once), Claude Code (`claude` installed and logged in)
  and/or [opencode](https://opencode.ai) (`opencode auth login` once). Or
  point `PI_BIN`, `CLAUDE_BIN` or `OPENCODE_BIN` at a compatible binary
- for self-running nights: `crontab` (install with `night-shift/schedule.py install`)

## First night

1. `python3 day-shift/new-order.py "My task"` and fill it in
2. Flip `status: draft` → `approved` — this is the handover
3. `python3 night-shift/run.py`
4. Tomorrow: `./day-shift/status.py` → review the diff → `./day-shift/accept.py 001`

The full shift checklists live in [`docs/runbook.md`](docs/runbook.md).
