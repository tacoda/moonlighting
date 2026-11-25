#!/usr/bin/env python3
"""moonlighting rotate-logs — gzip old night logs, never delete them.

Logs are the factory's append-only memory. This tool compresses log
files older than --days into the data directory's logs/archive/ so the directory
stays readable. Preview by default. Pass --write to rotate.

    moonlighting rotate-logs --days 90           # preview
    moonlighting rotate-logs --days 90 --write   # rotate
"""

from __future__ import annotations

import argparse
import gzip
import sys
import time

from . import factory


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Gzip old night logs into logs/archive/ (never deletes).")
    ap.add_argument("--days", type=int, default=90,
                    help="rotate files older than this many days (default: 90)")
    ap.add_argument("--write", action="store_true",
                    help="perform the rotation (default: preview only)")
    args = ap.parse_args()

    fl = factory.floor()
    logs = fl["logs"]
    if not logs.is_dir():
        factory.die(f"no logs directory: {logs}")
    archive = logs / "archive"
    cutoff = time.time() - args.days * 86400

    rotated = 0
    for path in sorted(logs.iterdir()):
        if not path.is_file() or path.stat().st_mtime >= cutoff:
            continue
        label = "rotated" if args.write else "would rotate"
        print(f"{label}: {path}")
        if not args.write:
            continue
        archive.mkdir(exist_ok=True)
        dest = archive / (path.name + ".gz")
        with gzip.open(dest, "wb") as f:
            f.write(path.read_bytes())
        path.unlink()
        rotated += 1

    if not args.write:
        print(f"{rotated} file(s) old enough to rotate")
        return
    print(f"{rotated} file(s) rotated into {archive}")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
