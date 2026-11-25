"""The moonlighting CLI: one command for every workflow.

    moonlighting night --engine pi
    moonlighting new-order "Title"

Run with --help to see every workflow. Everything runs through uv under
the hood when invoked from a checkout; the installed binary is standalone.
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

WORKFLOWS: dict[str, tuple[str, str]] = {
    # command name: (module, help line)
    "accept": ("accept", "Squash-merge a review order into its target repo."),
    "answer": ("answer", "Reply to a blocked order; it re-runs tonight."),
    "approve": ("approve", "Approve a draft order for the next night."),
    "feedback": ("feedback", "Send a review order back to blocked with notes."),
    "init": ("setup", "Set up the nWave guard, config file and data dirs."),
    "lint-orders": ("lint_orders",
                    "Check every order file against the template rules."),
    "new-order": ("new_order", "Create a work order interactively."),
    "night": ("run", "Run every approved order through the nWave guard."),
    "remove": ("remove", "Delete an order file; asks first unless --yes."),
    "rotate-logs": ("rotate_logs", "Compress and prune old night logs."),
    "schedule": ("schedule", "Install, remove or show the nightly cron entry."),
    "status": ("status", "Show the floor: orders, running locks, hints."),
}

err = Console(stderr=True, style="red")


def run_workflow(workflow: str, ctx: typer.Context) -> None:
    """Dispatch to a workflow module, forwarding the remaining args."""
    module = import_module(f"moonlighting.{workflow}")
    sys.argv = [sys.argv[0], *ctx.args]
    try:
        module.main()
    except factory.FactoryError as e:
        err.print(str(e))
        raise typer.Exit(code=e.code) from None


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Run factory workflows. See the subcommands below."""
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())


def _register(name: str) -> None:
    module, help_text = WORKFLOWS[name]

    @app.command(name, help=help_text, context_settings={
        "allow_extra_args": True, "ignore_unknown_options": True,
    })
    def dispatch(ctx: typer.Context,
                 module: str = typer.Option(module, hidden=True)) -> None:
        run_workflow(module, ctx)


for _name in WORKFLOWS:
    _register(_name)


if __name__ == "__main__":
    app()
