#!/usr/bin/env python3
"""factory status — factory floor report: what's queued, what needs you."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from moonlighting import factory


def branch_state(repo: factory.TargetRepo, branch: str) -> str:
    if not repo.branch_exists(branch):
        return ""
    base = repo.base_ref()
    behind, ahead = factory.git_out(
        repo.path, "rev-list", "--left-right", "--count",
        f"{base}...{branch}").split()
    return (f"branch {branch} in {repo.display()}: "
            f"{ahead} ahead of {base}, {behind} behind")


def show_locks(locks: Path) -> None:
    if not locks.is_dir():
        return
    rows = []
    for p in sorted(locks.glob("*.lock")):
        lines = p.read_text().splitlines()
        pid = lines[0].strip() if lines else ""
        what = lines[1].strip() if len(lines) > 1 else p.stem
        if pid.isdigit() and factory.pid_alive(int(pid)):
            rows.append(f"  running: {what} (pid {pid})")
    if rows:
        print("under way right now:")
        for r in rows:
            print(r)
        print()


def main() -> None:
    ap = argparse.ArgumentParser(description="Factory floor report.")
    ap.add_argument("--repo", default=None,
                    help="only show this repo's orders (path or URL)")
    args = ap.parse_args()

    root = factory.repo_root()
    orders_dir = factory.orders_dir(root)
    if not orders_dir.is_dir():
        factory.die(f"no work orders directory: {orders_dir} — set "
                    f"FACTORY_ORDERS_DIR or create it")

    show_locks(root / "night-shift" / "locks")

    filter_repo = (factory.TargetRepo.resolve(root, args.repo,
                                              update=False, soft=True)
                   if args.repo else None)

    orders = []
    for path in sorted(orders_dir.glob("*.md")):
        order = factory.WorkOrder(path, root)
        repo = factory.TargetRepo.resolve(root, order.repo_value,
                                          update=False, soft=True)
        if filter_repo is not None and (repo is None
                                        or repo.path != filter_repo.path):
            continue
        orders.append((order, repo))

    groups = [
        ("review — needs your decision:", "review",
         "→ review the branch, then factory accept ID (or factory feedback ID)"),
        ("blocked — waiting on you:", "blocked",
         "→ factory answer ID \"your answer\" — it re-approves for tonight"),
        ("approved — queued for tonight:", "approved",
         "→ factory night --repo <repo>"),
        ("draft — being written:", "draft", ""),
    ]

    print(f"factory floor — {datetime.now():%Y-%m-%d %H:%M}\n")
    closed = 0
    for label, status, hint in groups:
        rows = [(o, r) for o, r in orders if o.status == status]
        if not rows:
            continue
        print(label)
        for order, repo in rows:
            if repo is None:
                repo_tag = f"  [missing/uncloned: {order.repo_value}]"
            elif repo.path == root:
                repo_tag = ""
            else:
                repo_tag = f"  [{repo.display()}]"
            print(f"  {order.id}{repo_tag}  {order.title}")
            if repo is not None:
                state = branch_state(repo, order.branch)
                if state:
                    print(f"      {state}")
            if hint:
                print(f"      {hint.replace('ID', order.id)}")
        print()

    for order, _ in orders:
        if order.status in ("done", "rejected"):
            closed += 1
    if closed:
        print(f"done/rejected: {closed} closed\n")
    print("day-shift checklist: docs/runbook.md")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
