"""moonlighting reject ID REASON... — reject a work order from any state."""

from __future__ import annotations

import sys

from . import factory


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        factory.die("usage: moonlighting reject ID REASON...", 2)
    oid = args[0]
    reason = " ".join(args[1:])

    fl = factory.floor()
    matches = sorted(fl["orders"].glob(f"{oid}*.md"))
    if len(matches) != 1:
        factory.die(f"expected exactly one order matching '{oid}*', "
                    f"found {len(matches)}")
    order = factory.WorkOrder(matches[0])
    order.record_decision(f"rejected — {reason}")
    order.set_status("rejected")
    print(f"{order.id} rejected — the night only runs approved orders")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
