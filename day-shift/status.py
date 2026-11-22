#!/usr/bin/env python3
"""day-shift/status.py — factory floor report: what's queued, what needs you."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory  # noqa: E402


def branch_state(root: Path, branch: str) -> str:
    if factory.git(root, "show-ref", "--verify", "--quiet",
                   f"refs/heads/{branch}", check=False).returncode != 0:
        return ""
    behind, ahead = factory.git_out(
        root, "rev-list", "--left-right", "--count", f"main...{branch}").split()
    return f"branch {branch}: {ahead} ahead of main, {behind} behind"


def main() -> None:
    root = factory.repo_root()
    if not (root / "work-orders").is_dir():
        factory.die("no work-orders/ — not a factory floor")

    orders = {}
    for path in sorted((root / "work-orders").glob("*.md")):
        orders[path] = factory.parse_order(path)

    groups = [
        ("review — needs your decision:", "review",
         "→ git diff main...wo/ID && python3 day-shift/accept.py ID"),
        ("blocked — waiting on you:", "blocked",
         "→ answer in the order file, then set status: approved"),
        ("approved — queued for tonight:", "approved",
         "→ python3 night-shift/run.py"),
        ("draft — being written:", "draft", ""),
    ]

    print(f"factory floor — {datetime.now():%Y-%m-%d %H:%M}\n")
    closed = 0
    for label, status, hint in groups:
        rows = [(p, f) for p, f in orders.items() if f.get("status") == status]
        if not rows:
            continue
        print(label)
        for path, fields in rows:
            oid = fields.get("id", "?")
            branch = fields.get("branch") or f"wo/{oid}"
            print(f"  {oid}  {fields.get('title', '?')}")
            state = branch_state(root, branch)
            if state:
                print(f"      {state}")
            if hint:
                print(f"      {hint.replace('ID', oid)}")
        print()

    for fields in orders.values():
        if fields.get("status") in ("done", "rejected"):
            closed += 1
    if closed:
        print(f"done/rejected: {closed} closed\n")
    print("day-shift checklist: docs/runbook.md")


if __name__ == "__main__":
    main()
