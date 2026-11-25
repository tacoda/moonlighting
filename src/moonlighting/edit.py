"""moonlighting edit ID — open an order in $EDITOR, then lint it."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys

from . import factory


def main() -> None:
    if len(sys.argv) != 2:
        factory.die("usage: moonlighting edit ID", 2)
    oid = sys.argv[1]

    fl = factory.floor()
    matches = sorted(fl["orders"].glob(f"{oid}*.md"))
    if len(matches) != 1:
        factory.die(f"expected exactly one order matching '{oid}*', "
                    f"found {len(matches)}")
    path = matches[0]

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    subprocess.run(shlex.split(editor) + [str(path)], check=False)

    order = factory.WorkOrder(path)
    problems = order.lint()
    if problems:
        for p in problems:
            print(f"  - {p}")
        factory.die("lint problems remain — fix them before approving")
    print(f"{order.id} lint: clean")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
