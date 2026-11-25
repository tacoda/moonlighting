#!/usr/bin/env python3
"""moonlighting schedule — the night that starts itself.

Install/remove/inspect a cron entry that runs the night shift nightly.
The cron fires harmlessly when the queue is empty: no approved orders,
no model calls, no cost.

    moonlighting schedule install [--at "1 0"] [--max-orders 3]
    moonlighting schedule remove
    moonlighting schedule status

Requires crontab(1) and an authenticated host CLI in the cron environment
(paths are resolved and baked in at install time).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from . import factory

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


def install_cron() -> None:
    """Install (or replace) the nightly entry. Fire time, order cap and
    engine come from the config; there are no flags."""
    at = factory.factory_setting("schedule-at") or "1 0"
    raw_max = factory.factory_setting("schedule-max-orders") or "3"
    try:
        max_orders = int(raw_max)
    except ValueError:
        factory.die("config schedule-max-orders must be an integer", 2)
    try:
        minute, hour = (int(p) for p in at.split())
    except ValueError:
        factory.die("schedule-at takes 'minute hour', e.g. '17 1'", 2)
    if not (0 <= minute <= 59 and 0 <= hour <= 23):
        factory.die("schedule-at takes 'minute hour' in range "
                    "(minute 0-59, hour 0-23)", 2)

    engine = (os.environ.get("FACTORY_ENGINE")
              or factory.factory_setting("engine"))
    if not engine:
        factory.die("no engine defined — set engine in [factory] or run "
                    "with FACTORY_ENGINE")
    bin_var = f"{engine.upper()}_BIN"
    bin_val = os.environ.get(bin_var) or shutil.which(engine)
    if not bin_val:
        factory.die(f"{engine} not found on PATH (set {bin_var})")
    orders_env = os.environ.get("FACTORY_ORDERS_DIR")
    orders_part = f" FACTORY_ORDERS_DIR='{orders_env}'" if orders_env else ""
    cfg_env = os.environ.get(factory.CONFIG_ENV)
    cfg_part = f" MOONLIGHTING_CONFIG='{cfg_env}'" if cfg_env else ""

    mbin = shutil.which("moonlighting")
    if not mbin:
        factory.die("the moonlighting binary is not on PATH "
                    "(install with: uv tool install moonlighting-factory)")
    logs = factory.data_dir() / "logs"
    entry = (f"{minute} {hour} * * * {orders_part}{cfg_part} "
             f"{bin_var}='{os.path.abspath(bin_val)}' '{mbin}' night "
             f"--engine {engine} --max-orders {max_orders} "
             f">> '{logs / 'cron.log'}' 2>&1 {TAG}")

    kept = [line for line in current_crontab().splitlines() if TAG not in line]
    kept.append(entry)
    set_crontab("\n".join(kept) + "\n")
    print("night schedule installed:")
    print(f"  {entry}")
    print("the cron fires harmlessly when the queue is empty; "
          "remove with: moonlighting schedule remove")


def main() -> None:
    ap = argparse.ArgumentParser(description="Schedule the night shift via cron.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("install", help="install (or replace) the nightly entry "
                                   "from the config")
    sub.add_parser("remove", help="remove the nightly entry")
    sub.add_parser("status", help="show the nightly entry, if any")
    args = ap.parse_args()

    if args.cmd == "install":
        install_cron()
        return

    lines = current_crontab().splitlines()
    if args.cmd == "remove":
        kept = [line for line in lines if TAG not in line]
        set_crontab("\n".join(kept) + "\n" if kept else "")
        print("night schedule removed")
        return

    found = [line for line in lines if TAG in line]
    print("\n".join(found) if found else "not installed")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
