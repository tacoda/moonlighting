#!/usr/bin/env python3
"""day-shift/rotate-logs.py — gzip old night logs, never delete them.

Logs are the factory's append-only memory. This tool compresses log
files older than --days into night-shift/logs/archive/ so the directory
stays readable. Preview by default. Pass --write to rotate.

    uv run python day-shift/rotate-logs.py --days 90           # preview
    uv run python day-shift/rotate-logs.py --days 90 --write   # rotate
"""

from __future__ import annotations

import argparse
import gzip
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Gzip old night logs into logs/archive/ (never deletes).")
    ap.add_argument("--days", type=int, default=90,
                    help="rotate files older than this many days (default: 90)")
    ap.add_argument("--write", action="store_true",
                    help="perform the rotation (default: preview only)")
    args = ap.parse_args()

    root = factory.repo_root()
    logs = root / "night-shift" / "logs"
    if not logs.is_dir():
        factory.die(f"no logs directory: {logs}")
    archive = logs / "archive"
    cutoff = time.time() - args.days * 86400

    rotated = 0
    for path in sorted(logs.iterdir()):
        if not path.is_file() or path.stat().st_mtime >= cutoff:
            continue
        label = "rotated" if args.write else "would rotate"
        print(f"{label}: {path.relative_to(root)}")
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
    if rotated:
        factory.git(root, "add", "night-shift/logs")
        factory.git(root, "commit", "-q", "-m",
                    f"rotate-logs: archive {rotated} file(s) older than "
                    f"{args.days} days")
        print("rotation committed")
    print(f"{rotated} file(s) rotated into {archive.relative_to(root)}")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
