# moonlighting

A software factory where **people work the day shift and agents work the night
shift**. People decide. Agents type. The workforce is the engine you select
for the run: pi, Claude Code or opencode.

## How it works

Work moves through the factory as **work orders** — small markdown files
whose `status:` line is the contract between the shifts.
Marking an order `approved` is a standing instruction: tonight, an agent
executes it autonomously. In the morning it sits at `review` — with a report,
a branch, and a diff, waiting for a human decision.

```text
day shift (people)                     night shift (selected engine)
decide what problems matter  ──────►   implement approved orders
review branches & reports    ◄──────   flip orders to review/blocked
merge, block, or reject               never merge, never touch main
```

The whole lifecycle is one binary, `moonlighting`, with a subcommand per workflow:

```text
moonlighting new-order "Title"      create an order; it asks, then offers to approve
moonlighting status                 see every order: approved, blocked, review, draft, done
moonlighting approve ID             approve a draft
moonlighting night                  run the queue (--repo, --engine, --model, --max-orders)
moonlighting remove ID              delete an order file (a done order's record stays in the logs)
moonlighting accept ID              merge a reviewed order into its target repo
moonlighting answer ID "text"       answer a blocked order; it re-approves for tonight
moonlighting feedback ID "text"     send a review back with feedback; it goes to blocked
moonlighting lint-orders            check every order before spending tokens
moonlighting rotate-logs --days 90  gzip old logs (never deletes)
moonlighting schedule install       nightly cron at 00:01 (remove and status too)
```

uv runs everything under the hood. Commands work through
`uv run moonlighting ...` inside a factory checkout, or globally after
`uv tool install moonlighting-factory`.

## Layout

The binary works globally out of the box. Config lives at
`~/.config/moonlighting/config.toml`. State — orders, logs, locks,
sessions, cloned target repos — lives under
`~/.local/share/moonlighting/`. The night and QA manuals and the order
template ship inside the package. No git checkout is needed anywhere.

## Config

Every user keeps a config at `~/.config/moonlighting/config.toml` on their
own machine (`MOONLIGHTING_CONFIG` moves it). The file sets the engine,
models and orders directory, and binds repo names to paths and identities
through named profiles. Precedence: flags beat env vars beat the config
file. Copy [`docs/config-sample.toml`](docs/config-sample.toml) and fill in
your own names, repos and profiles. A commented sample lives at
[`docs/config-sample.toml`](docs/config-sample.toml).

## Layout

```text
src/moonlighting/       the package: factory model, workflows, engines,
                        manuals/ (NIGHT-SHIFT.md, QA-SHIFT.md),
                        templates/ (work-order-template.md)
tests/                  fake-based pytest suite (no git repos needed)
docs/runbook.md         shift checklists (morning, handover, forensics)
docs/flow.md            mermaid diagrams: the day/night work flow
docs/config-sample.toml every config key, commented
docs/work-order-template.md  how orders are written (reference copy)
PLAN.md                 phased roadmap
pyproject.toml          uv project; publishes the moonlighting command
AGENTS.md               standing instructions for any agent in this repo
```

## The rules

- The night shift executes only `approved` orders, each on its own branch (`wo/<id>`).
- Only the day shift merges code into a target repo's `main` (squash, via
  `moonlighting accept ID`). The factory never pushes. Run reports, QA
  packets and order status flips land under the data directory, never in
  anyone's repo.
- A blocked or ambiguous order stops the agent. It asks; it never guesses.
- The night shift produces **options, not answers**: when the problem is
  unknown, an order asks for variants, and the day shift decides among them.
- Orders can target other repos. The `repo:` frontmatter takes a config
  binding name, a path, or a git URL. URLs are cloned under the data
  directory and refreshed each night. Night work
  happens in a throwaway git worktree of the target repo — your working
  copies are never switched or touched. Only the day shift merges there, and
  the factory never pushes.

## Engines

Three hosts run the same work orders through the same flow:

| engine | headless invocation | sessions | model syntax |
| --- | --- | --- | --- |
| pi (default) | `pi --print` | deterministic: `wo-<id>` | `provider/id`, optional `:thinking` |
| claude | `claude -p` | uuid per order, kept in the data dir's `sessions.json` | alias or full model id |
| opencode | `opencode run` | host picks the id (`ses_...`), kept in the data dir's `sessions.json` | `provider/model#variant` |

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
  the data dir's `logs/*.events.jsonl`. The final report is extracted from it.
  Opt out with `FACTORY_JSON_AUDIT=0`.
- **QA pre-shift** — a second agent pass reviews the night's diff against the
  acceptance criteria and writes a verdict (SHIP/BLOCK/UNSURE) into the order
  file, so the morning decision takes minutes. Opt out with `FACTORY_QA=0`.

## Parallel nights

One night process runs per target repo. Processes run in parallel:

```bash
moonlighting night --repo ~/repos/shop
moonlighting night --repo git@github.com:acme/api.git --engine claude
```

Locks make collisions visible. One lock guards each target repo, plus one
global night lock. Run the processes side by side from the same install.
No extra checkouts, no conflicts.

## Requirements

- git, Python 3.11+, and [uv](https://docs.astral.sh/uv/). The package
depends only on `rich` and `typer`. uv runs everything: `uv sync` installs
the `moonlighting`
  command into the checkout, `uv run pytest` runs the suite. Publish to
  PyPI with `uv build` and `uv publish`.
- the host CLI for your selected engine, logged in. Pick [pi](https://pi.dev)
  (`pi` → `/login` once), Claude Code (`claude` installed and logged in)
  and/or [opencode](https://opencode.ai) (`opencode auth login` once). Or
  point `PI_BIN`, `CLAUDE_BIN` or `OPENCODE_BIN` at a compatible binary
- for self-running nights: `crontab` (install with `moonlighting schedule install`)

## First night

1. `moonlighting new-order "My task"` — answer the prompts, then approve
2. `moonlighting night`
3. Tomorrow: `moonlighting status` shows the verdicts. Review the diff, then
   `moonlighting accept ID`, `moonlighting feedback ID "..."` or
   `moonlighting answer ID "..."`
4. Optional: `moonlighting schedule install` runs the night daily at 00:01

The full shift checklists live in [`docs/runbook.md`](docs/runbook.md).
