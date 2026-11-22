#!/usr/bin/env python3
"""day-shift/accept.py NNN — squash-merge order NNN into its target repo, mark done."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        factory.die("usage: day-shift/accept.py NNN", 2)
    oid = sys.argv[1]

    root = factory.repo_root()
    matches = sorted((root / "work-orders").glob(f"{oid}*.md"))
    if len(matches) != 1:
        factory.die(f"expected exactly one work-orders/{oid}*.md, found {len(matches)}")
    order = matches[0]

    fields = factory.parse_order(order)
    status = fields.get("status", "")
    if status != "review":
        factory.die(f"{oid} is '{status}', not 'review' — decide blocked/draft "
                    f"orders in the order file first")

    target = factory.resolve_target(root, fields.get("repo"))
    branch = fields.get("branch") or f"wo/{oid}"
    t_display = factory.display_target(root, target)

    # target repo: must be clean, branch must carry work
    if not factory.clean_tree(target):
        factory.die(f"target repo is dirty: {t_display} — commit or stash there first")
    if factory.git(target, "show-ref", "--verify", "--quiet",
                   f"refs/heads/{branch}", check=False).returncode != 0:
        factory.die(f"branch {branch} does not exist in {t_display}")
    base = factory.local_main(target)
    ahead = int(factory.git_out(target, "rev-list", "--count",
                                f"{base}..{branch}") or "0")
    if ahead == 0:
        factory.die(f"{branch} has no commits ahead of {base} in {t_display} — "
                    f"nothing to merge")

    # factory repo: the bookkeeping commit happens here
    fbranch = factory.git_out(root, "branch", "--show-current")
    if fbranch != "main":
        factory.die(f"run accepts from the factory's main (you are on: {fbranch})")
    if not factory.clean_tree(root):
        factory.die("factory working tree must be clean")

    factory.git(target, "checkout", "-q", base)
    merge = factory.git(target, "merge", "--squash", branch, check=False)
    if merge.returncode != 0:
        print(merge.stdout + merge.stderr, file=sys.stderr)
        factory.die("squash-merge conflicts — resolve by hand in the target repo, "
                    f"or: git -C {t_display} merge --abort")

    title = fields.get("title", oid)
    commit_msg = f"wo-{oid}: {title} (night shift; accepted by day shift)"
    if target == root:
        # one commit: merged code + order marked done, in the factory's own history
        factory.set_status(order, "done")
        factory.git(root, "add", "-A")
        factory.git(root, "commit", "-q", "-m", commit_msg)
    else:
        # the work commits in the target repo (squash only stages it!);
        # the factory records the decision separately
        factory.git(target, "add", "-A")
        factory.git(target, "commit", "-q", "-m", commit_msg)
        factory.set_status(order, "done")
        factory.git(root, "add", str(order))
        factory.git(root, "commit", "-q", "-m", f"wo-{oid}: mark done (day shift)")

    print(f"accepted wo-{oid}: squash-merged {branch} into {base} in {t_display} "
          f"({ahead} commit(s)); order -> done")
    if target != root:
        print(f"remember: push {t_display} yourself — the factory never pushes")
        print(f"optional cleanup: git -C {t_display} branch -D {branch}")
    else:
        print(f"optional cleanup: git branch -D {branch}")


if __name__ == "__main__":
    main()
