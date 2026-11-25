"""The moonlighting CLI: one command for every workflow.

    moonlighting night --engine pi
    moonlighting new-order "Title"

Run with --dev to work on a factory checkout in the current directory.
Everything runs through uv under the hood.
"""

from __future__ import annotations

import os
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

WORKFLOWS = (
    "accept", "answer", "approve", "feedback", "lint-orders",
    "new-order", "night", "remove", "rotate-logs", "schedule", "status",
)

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
def main(
    ctx: typer.Context,
    dev: bool = typer.Option(
        False, "--dev", envvar="MOONLIGHTING_DEV",
        help="Work on a factory checkout in the current directory."),
):
    """Run factory workflows. See the subcommands below."""
    if dev:
        os.environ["MOONLIGHTING_DEV"] = "1"
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())


def _register(workflow: str) -> None:
    module = workflow.replace("-", "_")

    @app.command(workflow, context_settings={
        "allow_extra_args": True, "ignore_unknown_options": True,
    })
    def dispatch(ctx: typer.Context, module: str = module) -> None:
        run_workflow(module, ctx)


for _workflow in WORKFLOWS:
    _register(_workflow)


if __name__ == "__main__":
    app()
