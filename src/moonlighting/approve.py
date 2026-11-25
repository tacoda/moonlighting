"""moonlighting approve ID — approve a draft order for the next night."""

from __future__ import annotations

import sys

from . import factory


def main() -> None:
    if len(sys.argv) != 2:
        factory.die("usage: moonlighting approve ID", 2)
    oid = sys.argv[1]

    fl = factory.floor()
    base = fl["root"] or factory.data_dir()
    matches = sorted(fl["orders"].glob(f"{oid}*.md"))
    if len(matches) != 1:
        factory.die(f"expected exactly one order matching '{oid}*', "
                    f"found {len(matches)}")
    order = factory.WorkOrder(matches[0], base)
    if order.status != "draft":
        factory.die(f"{order.id} is '{order.status}', not 'draft' — "
                    f"only drafts get approved")
    order.set_status("approved")
    print(f"{order.id} approved — it runs on the next night")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
