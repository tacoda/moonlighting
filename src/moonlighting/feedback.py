"""moonlighting feedback ID MESSAGE... — alias of reply (review → blocked)."""

from __future__ import annotations

import sys

from . import factory, reply


def main() -> None:
    reply.main()


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
