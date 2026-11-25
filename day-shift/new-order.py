#!/usr/bin/env python3
"""day-shift/new-order.py TITLE — create the next work order from the template.

    python3 day-shift/new-order.py "Atom feed for the essays"
    python3 day-shift/new-order.py "Error contract" --repo ~/repos/lark

Picks the next free id, slugs the title into the filename, and fills the
frontmatter. Orders live outside git: the file lands in the orders
directory (default work-orders/, see FACTORY_ORDERS_DIR).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory  # noqa: E402


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:40] or "order"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create the next work order from the template.")
    ap.add_argument("title", help="short imperative title")
    ap.add_argument("--repo", default=None,
                    help="target repo (path or git URL) for the order")
    ap.add_argument("--model", default=None,
                    help="model string, passed verbatim to the engine")
    args = ap.parse_args()

    root = factory.repo_root()
    orders = factory.orders_dir(root)
    template = root / "docs" / "work-order-template.md"
    if not template.is_file():
        factory.die(f"missing template: {template}")
    orders.mkdir(parents=True, exist_ok=True)

    next_id = 1
    for path in orders.glob("*.md"):
        m = re.match(r"^(\d{3})", path.name)
        if m:
            next_id = max(next_id, int(m.group(1)) + 1)
    if next_id > 999:
        factory.die("no free 3-digit id left — archive old orders first")
    oid = f"{next_id:03d}"

    text = template.read_text()
    text = text.replace("id: NNN", f"id: {oid}", 1)
    text = text.replace("title: Short imperative title",
                        f"title: {args.title}", 1)
    text = text.replace("created: YYYY-MM-DD",
                        f"created: {date.today().isoformat()}", 1)
    text = text.replace("branch: wo/NNN", f"branch: wo/{oid}", 1)

    lines = text.splitlines()
    insert_at = None
    for i, line in enumerate(lines):
        if line.startswith("branch:"):
            insert_at = i + 1
    extra = []
    if args.repo:
        extra.append(f"repo: {args.repo}")
    if args.model:
        extra.append(f"model: {args.model}")
    if insert_at is not None:
        lines[insert_at:insert_at] = extra
    text = "\n".join(lines) + "\n"

    dest = orders / f"{oid}-{slugify(args.title)}.md"
    if dest.exists():
        factory.die(f"file already exists: {dest}")
    dest.write_text(text)

    order = factory.WorkOrder(dest, root)
    problems = order.lint()
    print(f"created {dest.relative_to(root)} (id {oid}, branch wo/{oid})")
    if problems:
        for p in problems:
            print(f"  - {p}")
        print("fix the problems above, then approve")
        sys.exit(1)
    print("lint: clean. Edit the body, then set status: approved to hand "
          "it to the night")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
