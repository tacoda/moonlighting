#!/usr/bin/env python3
"""night-shift/run.py — execute approved work orders with pi, headless.

Code lands on the order's branch; the day shift merges. Bookkeeping (status
flips, logs) is committed straight to main. See docs/runbook.md.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Execute approved work orders (night shift).")
    ap.add_argument("--max-orders", type=int, default=1,
                    help="run at most N orders (default: 1)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would run, change nothing")
    args = ap.parse_args()

    pi_bin = os.environ.get("PI_BIN", "pi")
    timeout_secs = int(os.environ.get("NIGHT_TIMEOUT_SECS", "7200"))

    root = factory.repo_root()
    os.chdir(root)

    if not (root / "work-orders").is_dir():
        factory.die("no work-orders/ directory — this is not a factory floor")

    branch = factory.git_out(root, "branch", "--show-current")
    if branch != "main":
        factory.die(f"start the night shift from main (you are on: {branch})")
    if not factory.clean_tree(root):
        factory.die("working tree must be clean before the night shift (commit or stash)")

    queue = []
    for order in sorted((root / "work-orders").glob("*.md")):
        if factory.parse_order(order).get("status") == "approved":
            queue.append(order)

    if not queue:
        print("nothing approved — nothing to do tonight.")
        return

    print("night shift queue:")
    for order in queue:
        print(f"  {order.relative_to(root)}")
    if args.dry_run:
        return

    logs = root / "night-shift" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    today = f"{datetime.now():%Y-%m-%d}"
    run_log = logs / f"{today}.md"

    ran = 0
    failed: str | None = None
    for order in queue:
        if ran >= args.max_orders:
            break
        rel = order.relative_to(root)
        fields = factory.parse_order(order)
        order_id = fields.get("id", "")
        if not order_id:
            print(f"skip {rel}: no id in frontmatter")
            continue
        order_branch = fields.get("branch") or f"wo/{order_id}"
        started = time.monotonic()

        print(f"\n=== wo-{order_id} : {rel} ===")

        exists = factory.git(root, "show-ref", "--verify", "--quiet",
                             f"refs/heads/{order_branch}", check=False).returncode == 0
        if exists:
            factory.git(root, "checkout", "-q", order_branch)
            print(f"resuming branch {order_branch}")
        else:
            factory.git(root, "checkout", "-q", "-b", order_branch, "main")
            print(f"new branch {order_branch}")

        outfile = logs / f"{today}-wo-{order_id}.out.md"
        errfile = logs / f"{today}-wo-{order_id}.err.log"

        cmd = [
            pi_bin, "--print", "--approve",
            "--append-system-prompt", "night-shift/NIGHT-SHIFT.md",
            "--session-id", f"wo-{order_id}",
            f"@{rel}",
            f"Execute work order {order_id} now, following the night-shift manual.",
        ]

        rc = 0
        try:
            with outfile.open("w") as out, errfile.open("w") as err:
                proc = subprocess.run(cmd, cwd=root, stdout=out, stderr=err,
                                      timeout=timeout_secs)
                rc = proc.returncode
        except subprocess.TimeoutExpired:
            rc = 124
        except FileNotFoundError:
            factory.git(root, "checkout", "-q", "main")
            factory.die(f"pi executable not found: {pi_bin} (set PI_BIN)", 127)

        secs = int(time.monotonic() - started)

        # The agent must leave a committed branch; sweep up anything it forgot
        # so the checkout back to main can't carry junk over.
        if not factory.clean_tree(root):
            factory.git(root, "add", "-A")
            factory.git(root, "commit", "-q", "-m",
                        f"wo-{order_id}: night-shift WIP (auto-committed by runner)")
            print(f"note: uncommitted work was auto-committed to {order_branch}")
        factory.git(root, "checkout", "-q", "main")

        new_status = "review" if rc == 0 else "blocked"

        with order.open("a") as f:
            f.write(f"\n### {datetime.now():%Y-%m-%d %H:%M} — night run, pi exit {rc} ({secs}s)\n\n")
            f.write(outfile.read_text())
            if rc != 0:
                f.write(f"\n> run FAILED (exit {rc}). stderr: {errfile.relative_to(root)}\n")

        factory.set_status(order, new_status)
        factory.git(root, "add", str(rel), "night-shift/logs")
        factory.git(root, "commit", "-q", "-m",
                    f"night-shift: wo-{order_id} -> {new_status} (exit {rc}, {secs}s)")

        print(f"wo-{order_id} -> {new_status} ({secs // 60}m{secs % 60:02d}s)")

        with run_log.open("a") as f:
            f.write(f"\n## {datetime.now():%H:%M} run\n")
            f.write(f"- wo-{order_id} ({rel}): {new_status}, pi exit {rc}, {secs}s — "
                    f"report in order file; raw: {outfile.relative_to(root)}\n")

        ran += 1
        if rc != 0:
            failed = order_id
            break

    print(f"\nnight shift over: {ran} order(s) processed.")
    if failed:
        print(f"wo-{failed} FAILED — marked blocked; run stopped. See {run_log.relative_to(root)}")
    print("morning: python3 day-shift/status.py")


if __name__ == "__main__":
    main()
