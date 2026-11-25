"""factory remove ID — delete a work order file (day shift only).

    moonlighting remove a1b2c3d
"""

from __future__ import annotations

import argparse
import sys

from . import factory


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Delete a work order file. The floor stays clean: "
                    "orders are untracked input.")
    ap.add_argument("id", help="order id prefix")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt")
    args = ap.parse_args()

    matches = sorted(factory.orders_dir().glob(f"{args.id}*.md"))
    if len(matches) != 1:
        factory.die(f"expected exactly one order matching '{args.id}*', "
                    f"found {len(matches)}")
    target = matches[0]
    order = factory.WorkOrder(target)
    note = ""
    if order.status == "done":
        note = " — the run logs keep its record"

    if args.yes:
        target.unlink()
        print(f"removed {target} [{order.status}]{note}")
        return

    if sys.stdin.isatty():
        answer = input(f"delete {target.name} [{order.status}]? [y/N]: ")
        if answer.strip().lower() in ("y", "yes"):
            target.unlink()
            print(f"removed {target}{note}")
            return
        print("kept")
        return

    factory.die("refusing to delete without --yes (or confirm interactively)")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
