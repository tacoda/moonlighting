#!/usr/bin/env python3
"""night-shift/schedule.py — the night that starts itself.

Install/remove/inspect a cron entry that runs the night shift nightly.
The cron fires harmlessly when the queue is empty: no approved orders,
no model calls, no cost.

    python3 night-shift/schedule.py install [--at "17 1"] [--max-orders 3]
    python3 night-shift/schedule.py remove
    python3 night-shift/schedule.py status

Requires crontab(1) and an authenticated host CLI in the cron environment
(paths are resolved and baked in at install time).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory  # noqa: E402

TAG = "# moonlighting-factory"


def current_crontab() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if r.returncode == 0:
        return r.stdout
    if "no crontab" in r.stderr:
        return ""
    factory.die(f"crontab -l failed: {r.stderr.strip()}")


def set_crontab(content: str) -> None:
    r = subprocess.run(["crontab", "-"], input=content,
                       capture_output=True, text=True)
    if r.returncode != 0:
        factory.die(f"crontab install failed: {r.stderr.strip()}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Schedule the night shift via cron.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    inst = sub.add_parser("install", help="install (or replace) the nightly entry")
    inst.add_argument("--at", default="17 1", metavar="MINUTE HOUR",
                      help="daily fire time (default: 17 1, i.e. 01:17)")
    inst.add_argument("--max-orders", type=int, default=3,
                      help="orders per night (default: 3)")
    inst.add_argument("--engine", default=os.environ.get("FACTORY_ENGINE", "pi"),
                      help="host agent: pi, claude or opencode (default pi). "
                           "env FACTORY_ENGINE")
    sub.add_parser("remove", help="remove the nightly entry")
    sub.add_parser("status", help="show the nightly entry, if any")
    args = ap.parse_args()

    root = factory.repo_root()
    lines = current_crontab().splitlines()
    kept = [line for line in lines if TAG not in line]

    if args.cmd == "remove":
        set_crontab("\n".join(kept) + "\n" if kept else "")
        print("night schedule removed")
        return

    if args.cmd == "status":
        found = [line for line in lines if TAG in line]
        print("\n".join(found) if found else "not installed")
        return

    try:
        minute, hour = args.at.split()
        minute, hour = int(minute), int(hour)
    except ValueError:
        factory.die("--at takes 'minute hour', e.g. --at '17 1'", 2)
    if not (0 <= minute <= 59 and 0 <= hour <= 23):
        factory.die("--at takes 'minute hour' in range (minute 0-59, hour 0-23)", 2)

    engine = args.engine
    bin_var = f"{engine.upper()}_BIN"
    bin_val = os.environ.get(bin_var) or shutil.which(engine)
    if not bin_val:
        factory.die(f"{engine} not found on PATH (set {bin_var})")
    entry = (f"{minute} {hour} * * * cd '{root}' "
             f"&& {bin_var}='{os.path.abspath(bin_val)}' "
             f"{sys.executable} night-shift/run.py --engine {engine} "
             f"--max-orders {args.max_orders} "
             f">> night-shift/logs/cron.log 2>&1 {TAG}")

    kept.append(entry)
    set_crontab("\n".join(kept) + "\n")
    print("night schedule installed:")
    print(f"  {entry}")
    print("the cron fires harmlessly when the queue is empty; "
          "remove with: python3 night-shift/schedule.py remove")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
