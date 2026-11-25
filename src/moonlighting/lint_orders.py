#!/usr/bin/env python3
"""moonlighting lint-orders — validate work orders before spending tokens.

Mechanical checks only: frontmatter, required fields, status vocabulary,
required sections, repo resolvability, duplicate ids. Judgment calls are
not lint's business. Exit 1 if anything fails.

The night runner lints approved orders automatically and blocks them
without spending tokens; this CLI is for the day shift, before approving.
"""

from __future__ import annotations

import sys

from . import factory


def main() -> None:
    fl = factory.floor()
    files = sorted(fl["orders"].glob("*.md"))
    if not files:
        print("no work orders")
        return

    seen: dict[str, str] = {}
    bad = 0
    for f in files:
        order = factory.WorkOrder(f)
        problems = order.lint()
        if order.id:
            if order.id in seen:
                problems.append(f"id {order.id} duplicates {seen[order.id]}")
            seen[order.id] = f.name
        if problems:
            bad += 1
            print(order.rel)
            for p in problems:
                print(f"  - {p}")

    if bad:
        print(f"\n{bad} of {len(files)} order(s) with problems")
        sys.exit(1)
    print(f"all {len(files)} orders clean")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
