"""The moonlighting CLI: one command for every workflow.

    moonlighting night --engine pi
    moonlighting new-order "Title"

Run --help on any command to see its arguments and options.
"""

from __future__ import annotations

import sys
from importlib import import_module

import typer
from rich.console import Console

from . import factory

app = typer.Typer(
    help="moonlighting — a software factory. People decide, agents type.",
    no_args_is_help=True,
    add_completion=False,
)

err = Console(stderr=True, style="red")

FORWARD = {"allow_extra_args": True, "ignore_unknown_options": True}

ID_HELP = "Work order id. A unique prefix is enough."
MSG_HELP = "The reply text. Every word after the id joins into one message."


def _forward(ctx: typer.Context, module_name: str,
             tokens: list[str] | None = None,
             opts: list[tuple[str, object]] | None = None) -> None:
    """Run a workflow module. Declared values are rebuilt into argv ahead
    of anything extra the module still parses itself."""
    argv = [sys.argv[0], *(tokens or [])]
    for flag, value in opts or []:
        if value in (None, False):
            continue
        argv.append(flag)
        if value is not True:
            argv.append(str(value))
    argv += ctx.args
    sys.argv = argv
    try:
        import_module(f"moonlighting.{module_name}").main()
    except factory.FactoryError as e:
        err.print(str(e))
        raise typer.Exit(code=e.code) from None


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Run factory workflows. See the subcommands below."""
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())


@app.command("accept", help="Squash-merge a review order into its target repo.",
             context_settings=FORWARD)
def accept_cmd(ctx: typer.Context,
               order_id: str = typer.Argument(..., help=ID_HELP)):
    _forward(ctx, "accept", [order_id])


@app.command("answer", help="Reply to a blocked order. It re-runs tonight.",
             context_settings=FORWARD)
def answer_cmd(ctx: typer.Context,
               order_id: str = typer.Argument(..., help=ID_HELP),
               message: list[str] | None = typer.Argument(None, help=MSG_HELP)):
    _forward(ctx, "answer", [order_id, *(message or [])])


@app.command("approve", help="Approve a draft order for the next night.",
             context_settings=FORWARD)
def approve_cmd(ctx: typer.Context,
                order_id: str = typer.Argument(..., help=ID_HELP)):
    _forward(ctx, "approve", [order_id])


@app.command("edit", help="Open an order in $EDITOR, then lint it.",
             context_settings=FORWARD)
def edit_cmd(ctx: typer.Context,
             order_id: str = typer.Argument(..., help=ID_HELP)):
    _forward(ctx, "edit", [order_id])


@app.command("feedback", help="Send a review order back to blocked, with notes.",
             context_settings=FORWARD)
def feedback_cmd(ctx: typer.Context,
                 order_id: str = typer.Argument(..., help=ID_HELP),
                 message: list[str] | None = typer.Argument(None, help=MSG_HELP)):
    _forward(ctx, "feedback", [order_id, *(message or [])])


@app.command("init", help="Report the bundled nWave guard, then set up "
             "the config file and the data dirs.", context_settings=FORWARD)
def init_cmd(ctx: typer.Context,
             cron: bool | None = typer.Option(
                 None, "--cron/--no-cron",
                 help="Install the nightly cron without asking, or skip it "
                 "without asking.")):
    flags = []
    if cron is True:
        flags.append("--cron")
    elif cron is False:
        flags.append("--no-cron")
    _forward(ctx, "setup", [], [(flag, True) for flag in flags])


@app.command("lint-orders", help="Check every order file against the "
             "template rules.", context_settings=FORWARD)
def lint_orders_cmd(ctx: typer.Context):
    _forward(ctx, "lint_orders")


@app.command("new-order", help="Create a work order.", context_settings=FORWARD)
def new_order_cmd(ctx: typer.Context,
                  title: str | None = typer.Argument(
                      None, help="Short imperative title. Asked for "
                      "interactively when omitted."),
                  repo: str | None = typer.Option(
                      None, "--repo",
                      help="Target repo: a config binding name, a path, or "
                      "a git URL."),
                  model: str | None = typer.Option(
                      None, "--model",
                      help="Model string for the engine, in that engine's "
                      "own syntax."),
                  approve: bool = typer.Option(
                      False, "--approve",
                      help="Approve the order for tonight right away."),
                  draft: bool = typer.Option(
                      False, "--draft", help="Leave the order as a draft."),
                  body: str | None = typer.Option(
                      None, "--body",
                      help="Markdown text appended to the order body."),
                  body_file: str | None = typer.Option(
                      None, "--body-file",
                      help="Read body content from this file. '-' reads "
                      "stdin."),
                  engine: str | None = typer.Option(
                      None, "--engine",
                      help="Harness for this order. Beats the repo binding "
                      "and the factory setting."),
                  qa_model: str | None = typer.Option(
                      None, "--qa-model",
                      help="QA model for this order.")):
    _forward(ctx, "new_order", [title] if title else [],
             [("--repo", repo), ("--model", model),
              ("--approve", approve), ("--draft", draft),
              ("--body", body), ("--body-file", body_file),
              ("--engine", engine), ("--qa-model", qa_model)])


@app.command("night", help="Run every approved order through the nWave guard.",
             context_settings=FORWARD)
def night_cmd(ctx: typer.Context,
              engine: str | None = typer.Option(
                  None, "--engine",
                  help="Host agent: pi, claude, opencode, codex, or any configured harness. Env "
                  "FACTORY_ENGINE, or the config file, then pi."),
              model: str | None = typer.Option(
                  None, "--model",
                  help="Model string for the run, in the engine's own "
                  "syntax. Env FACTORY_MODEL, or the config file."),
              qa_model: str | None = typer.Option(
                  None, "--qa-model",
                  help="Separate model for the QA pass. Falls back to the "
                  "run model. Env FACTORY_QA_MODEL, or the config file."),
              repo: str | None = typer.Option(
                  None, "--repo", help="Only run orders for this target repo."),
              max_orders: int | None = typer.Option(
                  None, "--max-orders", min=1,
                  help="Stop after N orders. Default 1."),
              dry_run: bool = typer.Option(
                  False, "--dry-run",
                  help="List what would run. Change nothing.")):
    _forward(ctx, "run", [],
             [("--engine", engine), ("--model", model),
              ("--qa-model", qa_model), ("--repo", repo),
              ("--max-orders", max_orders), ("--dry-run", dry_run)])


@app.command("reject", help="Reject an order from any state, with a reason.",
             context_settings=FORWARD)
def reject_cmd(ctx: typer.Context,
               order_id: str = typer.Argument(..., help=ID_HELP),
               message: list[str] | None = typer.Argument(
                   None, help="Why the order is rejected.")):
    _forward(ctx, "reject", [order_id, *(message or [])])


@app.command("remove", help="Delete an order file. Asks first unless --yes.",
             context_settings=FORWARD)
def remove_cmd(ctx: typer.Context,
               order_id: str = typer.Argument(..., help=ID_HELP),
               yes: bool = typer.Option(
                   False, "--yes", help="Delete without the prompt.")):
    _forward(ctx, "remove", [order_id], [("--yes", yes)])


@app.command("rotate-logs", help="Gzip old night logs into logs/archive/.",
             context_settings=FORWARD)
def rotate_logs_cmd(ctx: typer.Context,
                    days: int | None = typer.Option(
                        None, "--days", min=1,
                        help="Rotate files older than this many days. "
                        "Default 90."),
                    write: bool = typer.Option(
                        False, "--write",
                        help="Rotate for real. Default is a preview.")):
    _forward(ctx, "rotate_logs", [],
             [("--days", days), ("--write", write)])


@app.command("schedule", help="Install, remove or show the nightly cron "
             "entry. Shapes: schedule install [--at MINUTE HOUR] "
             "[--engine E] [--model M] [--qa-model Q] [--max-orders N], "
             "schedule remove, schedule status.", context_settings=FORWARD)
def schedule_cmd(ctx: typer.Context):
    _forward(ctx, "schedule")


@app.command("show", help="Print one order file.",
             context_settings=FORWARD)
def show_cmd(ctx: typer.Context,
             order_id: str = typer.Argument(..., help=ID_HELP)):
    _forward(ctx, "show", [order_id])


@app.command("status", help="Show the floor: orders, running locks, hints.",
             context_settings=FORWARD)
def status_cmd(ctx: typer.Context,
               repo: str | None = typer.Option(
                   None, "--repo", help="Only show orders for this repo."),
               as_json: bool = typer.Option(
                   False, "--json", help="Print the orders as JSON, for tools.")):
    _forward(ctx, "status", [], [("--repo", repo), ("--json", as_json)])


if __name__ == "__main__":
    app()
