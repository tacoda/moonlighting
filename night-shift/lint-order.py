#!/usr/bin/env python3
"""night-shift/lint-order.py — validate work orders before spending tokens.

Mechanical checks only: frontmatter, required fields, status vocabulary,
required sections, repo resolvability, duplicate ids. Judgment calls are
not lint's business. Exit 1 if anything fails.

The night runner lints approved orders automatically and blocks them
without spending tokens; this CLI is for the day shift, before approving.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory  # noqa: E402


def main() -> None:
    root = factory.repo_root()
    files = sorted((root / "work-orders").glob("*.md"))
    if not files:
        print("no work orders")
        return

    seen: dict[str, str] = {}
    bad = 0
    for f in files:
        problems = factory.lint_order(f, root)
        oid = factory.parse_order(f).get("id", "")
        if oid:
            if oid in seen:
                problems.append(f"id {oid} duplicates {seen[oid]}")
            seen[oid] = f.name
        if problems:
            bad += 1
            print(f"{f.relative_to(root)}")
            for p in problems:
                print(f"  - {p}")

    if bad:
        print(f"\n{bad} of {len(files)} order(s) with problems")
        sys.exit(1)
    print(f"all {len(files)} orders clean")


if __name__ == "__main__":
    main()
