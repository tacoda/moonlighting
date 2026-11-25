"""moonlighting answer ID MESSAGE... — answer a blocked order and re-approve it.

    moonlighting answer a1b2c3d use the other path
"""

from __future__ import annotations

import sys

from . import factory


def main() -> None:
    if len(sys.argv) < 3:
        factory.die("usage: moonlighting answer ID MESSAGE...", 2)
    oid = sys.argv[1]
    message = " ".join(sys.argv[2:])

    fl = factory.floor()
    matches = sorted(fl["orders"].glob(f"{oid}*.md"))
    if len(matches) != 1:
        factory.die(f"expected exactly one order matching '{oid}*', "
                    f"found {len(matches)}")
    order = factory.WorkOrder(matches[0])

    if order.status != "blocked":
        factory.die(f"{order.id} is '{order.status}', not 'blocked' — "
                    f"nothing to answer")
    order.record_decision(message)
    order.set_status("approved")
    print(f"{order.id}: answer recorded, re-approved for tonight")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
