"""moonlighting reply ID MESSAGE... — the one day-shift reply.

On a review order the reply parks it as blocked with your notes. On a
blocked order the reply answers the notes and re-approves it. feedback
and answer are aliases of this command.
"""

from __future__ import annotations

import sys

from . import factory


def reply(oid: str, message: str) -> str:
    fl = factory.floor()
    matches = sorted(fl["orders"].glob(f"{oid}*.md"))
    if len(matches) != 1:
        factory.die(f"expected exactly one order matching '{oid}*', "
                    f"found {len(matches)}")
    order = factory.WorkOrder(matches[0])
    old = order.status
    if old == "review":
        new_status = "blocked"
    elif old == "blocked":
        new_status = "approved"
    else:
        factory.die(f"{order.id} is '{old}' — reply needs a review or "
                    f"blocked order")
    order.record_decision(f"{old} → {new_status}: {message}")
    order.set_status(new_status)
    return f"{order.id}: {old} → {new_status}"


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        factory.die("usage: moonlighting reply ID MESSAGE...", 2)
    print(reply(args[0], " ".join(args[1:])))


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
