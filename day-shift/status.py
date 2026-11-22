#!/usr/bin/env python3
"""day-shift/status.py — factory floor report: what's queued, what needs you."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory  # noqa: E402


def branch_state(root: Path, target: Path, branch: str) -> str:
    if factory.git(target, "show-ref", "--verify", "--quiet",
                   f"refs/heads/{branch}", check=False).returncode != 0:
        return ""
    base = factory.base_ref(root, target)
    behind, ahead = factory.git_out(
        target, "rev-list", "--left-right", "--count", f"{base}...{branch}").split()
    return (f"branch {branch} in {factory.display_target(root, target)}: "
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
    ap.add_argument("--repo", default=None, help="only show this repo's orders (path or URL)")
    args = ap.parse_args()

    root = factory.repo_root()
    if not (root / "work-orders").is_dir():
        factory.die("no work-orders/ — not a factory floor")

    show_locks(root / "night-shift" / "locks")

    filter_target = (factory.resolve_target(root, args.repo, update=False, soft=True)
                     if args.repo else None)

    orders = {}
    for path in sorted((root / "work-orders").glob("*.md")):
        fields = factory.parse_order(path)
        target = factory.resolve_target(root, fields.get("repo"), update=False, soft=True)
        if filter_target is not None and target != filter_target:
            continue
        orders[path] = (fields, target)

    groups = [
        ("review — needs your decision:", "review",
         "→ review the branch in the target repo, then python3 day-shift/accept.py ID"),
        ("blocked — waiting on you:", "blocked",
         "→ answer in the order file, then set status: approved"),
        ("approved — queued for tonight:", "approved",
         "→ python3 night-shift/run.py --repo <repo>"),
        ("draft — being written:", "draft", ""),
    ]

    print(f"factory floor — {datetime.now():%Y-%m-%d %H:%M}\n")
    closed = 0
    for label, status, hint in groups:
        rows = [(p, f, t) for p, (f, t) in orders.items() if f.get("status") == status]
        if not rows:
            continue
        print(label)
        for path, fields, target in rows:
            oid = fields.get("id", "?")
            branch = fields.get("branch") or f"wo/{oid}"
            if target is None:
                repo_tag = f"  [missing/uncloned: {fields.get('repo')}]"
            elif target == root:
                repo_tag = ""
            else:
                repo_tag = f"  [{factory.display_target(root, target)}]"
            print(f"  {oid}{repo_tag}  {fields.get('title', '?')}")
            if target is not None:
                state = branch_state(root, target, branch)
                if state:
                    print(f"      {state}")
            if hint:
                print(f"      {hint.replace('ID', oid)}")
        print()

    for fields, _ in orders.values():
        if fields.get("status") in ("done", "rejected"):
            closed += 1
    if closed:
        print(f"done/rejected: {closed} closed\n")
    print("day-shift checklist: docs/runbook.md")


if __name__ == "__main__":
    main()
