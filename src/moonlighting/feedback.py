"""moonlighting feedback ID MESSAGE... — send a review back with feedback.

    moonlighting feedback a1b2c3d add tests for the empty case
"""

from __future__ import annotations

import sys

from . import factory


def main() -> None:
    if len(sys.argv) < 3:
        factory.die("usage: moonlighting feedback ID MESSAGE...", 2)
    oid = sys.argv[1]
    message = " ".join(sys.argv[2:])

    fl = factory.floor()
    matches = sorted(fl["orders"].glob(f"{oid}*.md"))
    if len(matches) != 1:
        factory.die(f"expected exactly one order matching '{oid}*', "
                    f"found {len(matches)}")
    order = factory.WorkOrder(matches[0])

    if order.status != "review":
        factory.die(f"{order.id} is '{order.status}', not 'review' — "
                    f"feedback goes to review orders")
    order.record_decision(message)
    order.set_status("blocked")
    print(f"{order.id}: feedback recorded, sent back to blocked")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
