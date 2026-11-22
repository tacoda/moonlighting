# moonlighting

A software factory where **people work the day shift and agents work the night
shift**. People decide; agents type. [Pi](https://pi.dev) is the workforce.

## How it works

Work moves through the factory as **work orders** — small markdown files in
`work-orders/` whose `status:` line is the contract between the shifts.
Marking an order `approved` is a standing instruction: tonight, an agent
executes it autonomously. In the morning it sits at `review` — with a report,
a branch, and a diff, waiting for a human decision.

```
day shift (people)                     night shift (pi agents)
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
work-orders/            one markdown file per unit of work (NNN-title.md)
night-shift/run.py      the night runner (headless pi or claude)
night-shift/NIGHT-SHIFT.md   the night agent's operating manual
night-shift/logs/       run reports and raw agent output (append-only)
night-shift/sessions.json   engine session ids per order (claude engine)
night-shift/locks/      run locks (gitignored)
repos/                  target repos cloned from git URLs (gitignored)
day-shift/status.py     factory floor report
day-shift/accept.py     squash-merge a reviewed order into its target repo
factory.py              shared helpers for the factory scripts
docs/work-order-template.md  how orders are written
docs/runbook.md         shift checklists (morning, handover, forensics)
PLAN.md                 phased roadmap
AGENTS.md               standing instructions for any agent in this repo
```

## The rules

- The night shift executes only `approved` orders, each on its own branch (`wo/NNN`).
- Only the day shift merges code into `main` (squash, via `day-shift/accept.sh`).
  Night bookkeeping (status flips, run logs) commits straight to `main` — but never contains code.
- A blocked or ambiguous order stops the agent. It asks; it never guesses.
- The night shift produces **options, not answers**: when the problem is
  unknown, an order asks for variants, and the day shift decides among them.
- Orders can target other repos: `repo:` frontmatter takes a path or a git
  URL (URLs are cloned under `repos/` and refreshed each night). Night work
  happens on the order's branch inside the target repo; only the day shift
  merges there, and the factory never pushes.

## Engines

Both hosts run the same work orders through the same flow:

| engine | headless invocation | sessions |
|---|---|---|
| pi (default) | `pi --print` | deterministic: `wo-NNN` |
| claude | `claude -p` | uuid per order, kept in `night-shift/sessions.json` |

Pick per run with `--engine` (or `FACTORY_ENGINE`). Both run under the nWave
tool-call guard (`nwave-ai mode all`); agent commits carry nWave attribution.

## Several factories, several repos

One factory process per target repo; processes run in parallel:

```bash
python3 night-shift/run.py --repo ~/repos/shop
python3 night-shift/run.py --repo git@github.com:acme/api.git --engine claude
```

Locks make collisions visible: one night per target repo, one night per
factory checkout. For true parallel nights, clone this factory once per repo
and run one process in each. The morning is still one command:

```bash
python3 day-shift/status.py
```

## Requirements

- [pi](https://pi.dev) installed and logged in (run `pi` once, `/login`) —
  or point `PI_BIN` at any compatible CLI
- git; Python 3.9+ (stdlib only — nothing to pip install)
- one or both host CLIs: [pi](https://pi.dev) (`pi` → `/login` once) and/or
  Claude Code (`claude` installed and logged in)

## First night

1. `cp docs/work-order-template.md work-orders/001-my-task.md` and fill it in
2. Flip `status: draft` → `approved` — this is the handover
3. `./night-shift/run.sh`
4. Tomorrow: `./day-shift/status.py` → review the diff → `./day-shift/accept.py 001`

The full shift checklists live in [`docs/runbook.md`](docs/runbook.md).
