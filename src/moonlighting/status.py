#!/usr/bin/env python3
"""moonlighting status — factory floor report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import factory

console = Console()

STATUS_STYLE = {"approved": "green", "review": "yellow", "blocked": "red",
                "draft": "cyan", "done": "dim", "rejected": "dim"}

HINTS = {
    "review": "moonlighting accept ID, or moonlighting feedback ID with changes",
    "blocked": "moonlighting answer ID with your reply",
    "approved": "runs on the next night",
    "draft": "moonlighting approve ID when ready",
}


def branch_state(repo: factory.TargetRepo, branch: str) -> str:
    if not repo.branch_exists(branch):
        return ""
    base = repo.base_ref()
    behind, ahead = factory.git_out(
        repo.path, "rev-list", "--left-right", "--count",
        f"{base}...{branch}").split()
    return f"{ahead} ahead of {base}, {behind} behind"


def show_locks(locks: Path) -> None:
    if not locks.is_dir():
        return
    for p in sorted(locks.glob("*.lock")):
        lines = p.read_text().splitlines()
        pid = lines[0].strip() if lines else ""
        what = lines[1].strip() if len(lines) > 1 else p.stem
        if pid.isdigit() and factory.pid_alive(int(pid)):
            console.print(f"[yellow]running:[/yellow] {what} (pid {pid})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Factory floor report.")
    ap.add_argument("--repo", default=None,
                    help="only show orders for this repo (name or path)")
    ap.add_argument("--json", action="store_true",
                    help="print the orders as JSON, for tools")
    args = ap.parse_args()

    fl = factory.floor()
    orders = fl["orders"]

    if not args.json:
        console.print(f"[bold]factory floor[/bold] — {datetime.now():%Y-%m-%d %H:%M}")
        show_locks(fl["locks"])

    filter_repo = None
    if args.repo:
        filter_repo = factory.TargetRepo.resolve(args.repo,
                                                 update=False, soft=True)

    rows = []
    closed = 0
    for path in sorted(orders.glob("*.md")):
        order = factory.WorkOrder(path)
        repo = None
        if order.repo_value:
            repo = factory.TargetRepo.resolve(order.repo_value,
                                              update=False, soft=True)
        if filter_repo is not None and (repo is None
                                        or repo.path != filter_repo.path):
            continue
        target = repo.display() if repo else "(no target repo)"
        if repo is None and order.repo_value:
            target = f"missing: {order.repo_value}"
        state = ""
        if repo is not None and order.status in ("approved", "review", "blocked"):
            state = branch_state(repo, order.branch)
        rows.append((order.id, order.title, order.status, target, state))
        if order.status in ("done", "rejected"):
            closed += 1

    if args.json:
        keys = ("id", "title", "status", "target", "branch")
        print(json.dumps([dict(zip(keys, row)) for row in rows]))
        return

    if rows:
        table = Table(show_header=True, header_style="bold")
        for col in ("id", "title", "status", "target", "branch"):
            table.add_column(col)
        for oid, title, status, target, state in rows:
            style = STATUS_STYLE.get(status, "")
            table.add_row(oid, title,
                          f"[{style}]{status}[/{style}]" if style else status,
                          target, state)
        console.print(table)
        for oid, _t, status, _tg, _st in rows:
            hint = HINTS.get(status)
            if hint:
                console.print(f"[dim]{oid}: {hint}[/dim]")
    else:
        console.print(f"no orders in {orders}. "
                      "Create one with `moonlighting new-order`.")

    if closed:
        console.print(f"[dim]{closed} closed (done or rejected)[/dim]")
    console.print("[dim]checklists: docs/runbook.md[/dim]")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(e.code)
