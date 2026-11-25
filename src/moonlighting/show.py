"""moonlighting show ID — print one order file."""

from __future__ import annotations

import sys

from . import factory


def main() -> None:
    if len(sys.argv) != 2:
        factory.die("usage: moonlighting show ID", 2)
    oid = sys.argv[1]

    fl = factory.floor()
    matches = sorted(fl["orders"].glob(f"{oid}*.md"))
    if len(matches) != 1:
        factory.die(f"expected exactly one order matching '{oid}*', "
                    f"found {len(matches)}")
    text = matches[0].read_text()
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
