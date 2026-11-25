#!/usr/bin/env python3
"""moonlighting new-order TITLE — create the next work order from the template.

    moonlighting new-order "Atom feed for the essays"
    moonlighting new-order "Error contract" --repo ~/repos/lark

Generates a unique sha id, slugs the title into the filename, and fills
the frontmatter. The order lands in the orders directory. The default
location is tracked in the factory repo, and FACTORY_ORDERS_DIR moves it.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
import uuid
from datetime import date
from pathlib import Path

from . import factory


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:40] or "order"


def make_id() -> str:
    digest = hashlib.sha256(f"{time.time_ns()}:{uuid.uuid4()}".encode())
    return digest.hexdigest()[:7]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create the next work order from the template.")
    ap.add_argument("title", nargs="?", default=None,
                    help="short imperative title (asked for interactively)")
    ap.add_argument("--repo", default=None,
                    help="target repo (path or git URL) for the order")
    ap.add_argument("--model", default=None,
                    help="model string, passed verbatim to the engine")
    ap.add_argument("--approve", action="store_true",
                    help="set status: approved right away")
    ap.add_argument("--draft", action="store_true",
                    help="keep status: draft, skip the approval question")
    ap.add_argument("--body", default=None,
                    help="markdown text appended to the order body")
    ap.add_argument("--body-file", default=None, dest="body_file",
                    help="read body content from this file ('-' reads stdin)")
    ap.add_argument("--engine", default=None,
                    help="harness for this order (beats repo and factory settings)")
    ap.add_argument("--qa-model", default=None, dest="qa_model",
                    help="QA model for this order")
    args = ap.parse_args()
    if args.approve and args.draft:
        factory.die("--approve and --draft cannot be combined", 2)
    if args.body is not None and args.body_file is not None:
        factory.die("--body and --body-file cannot be combined", 2)
    interactive = sys.stdin.isatty()

    def ask(prompt: str) -> str:
        try:
            return input(prompt).strip()
        except EOFError:
            return ""

    title = args.title
    if not title:
        if not interactive:
            ap.error("title is required when not running interactively")
        title = ask("title (short imperative): ")
    if not title:
        factory.die("a title is required")
    repo = args.repo
    model = args.model
    if interactive:
        if repo is None:
            repo = ask("target repo, path or URL (enter for this factory): ") or None
        if model is None:
            model = ask("model for the engine (enter for the host default): ") or None

    orders = factory.orders_dir()
    template = factory.packaged_template()
    orders.mkdir(parents=True, exist_ok=True)

    taken = {path.name.split("-")[0] for path in orders.glob("*.md")}
    oid = make_id()
    while oid in taken:
        oid = make_id()

    text = template.read_text()
    text = text.replace("id: NNN", f"id: {oid}", 1)
    text = text.replace("title: Short imperative title",
                        f"title: {title}", 1)
    text = text.replace("created: YYYY-MM-DD",
                        f"created: {date.today().isoformat()}", 1)
    text = text.replace("branch: wo/NNN", f"branch: wo/{oid}", 1)

    lines = text.splitlines()
    insert_at = None
    for i, line in enumerate(lines):
        if line.startswith("branch:"):
            insert_at = i + 1
    extra = []
    if repo:
        extra.append(f"repo: {repo}")
    if model:
        extra.append(f"model: {model}")
    if args.engine:
        extra.append(f"engine: {args.engine}")
    if args.qa_model:
        extra.append(f"qa-model: {args.qa_model}")
    if insert_at is not None:
        lines[insert_at:insert_at] = extra
    text = "\n".join(lines) + "\n"

    body = args.body
    if args.body_file is not None:
        if args.body_file == "-":
            body = sys.stdin.read()
        else:
            source = Path(args.body_file).expanduser()
            if not source.is_file():
                factory.die(f"body file not found: {source}")
            body = source.read_text()
    if body and body.strip():
        text = text.rstrip("\n") + "\n\n" + body.strip() + "\n"

    dest = orders / f"{oid}-{slugify(title)}.md"
    if dest.exists():
        factory.die(f"file already exists: {dest}")
    dest.write_text(text)

    order = factory.WorkOrder(dest)
    problems = order.lint()
    print(f"created {dest} (id {oid}, branch wo/{oid})")
    if problems:
        for p in problems:
            print(f"  - {p}")
        print("fix the problems above, then approve")
        sys.exit(1)
    print("lint: clean. Edit the body before the night runs it.")

    def approve_now() -> None:
        factory.set_status(dest, "approved")
        print("status: approved — the night picks it up")

    if args.approve:
        approve_now()
    elif args.draft:
        print("left as draft")
    elif interactive:
        answer = ask("approve now for tonight? [y/N]: ").lower()
        if answer in ("y", "yes"):
            approve_now()
        else:
            print("left as draft. Set status: approved when ready.")
    else:
        print("set status: approved to hand it to the night")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
