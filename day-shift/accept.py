#!/usr/bin/env python3
"""day-shift/accept.py NNN — squash-merge order NNN into its target repo, mark done."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        factory.die("usage: day-shift/accept.py NNN", 2)
    oid = sys.argv[1]

    root = factory.repo_root()
    matches = sorted(factory.orders_dir(root).glob(f"{oid}*.md"))
    if len(matches) != 1:
        factory.die(f"expected exactly one work-orders/{oid}*.md, "
                    f"found {len(matches)}")
    order = factory.WorkOrder(matches[0], root)

    if order.status != "review":
        factory.die(f"{oid} is '{order.status}', not 'review' — decide "
                    f"blocked/draft orders in the order file first")

    repo = factory.TargetRepo.resolve(root, order.repo_value)
    if repo is None:
        factory.die(f"cannot resolve repo '{order.repo_value}' for {oid}")
    branch = order.branch
    t_display = repo.display()

    if not repo.branch_exists(branch):
        factory.die(f"branch {branch} does not exist in {t_display}")
    base = repo.local_main()
    ahead = int(factory.git_out(repo.path, "rev-list", "--count",
                                f"{base}..{branch}") or "0")
    if ahead == 0:
        factory.die(f"{branch} has no commits ahead of {base} in {t_display} — "
                    f"nothing to merge")

    fbranch = factory.git_out(root, "branch", "--show-current")
    if fbranch != "main":
        factory.die(f"run accepts from the factory's main (you are on: {fbranch})")
    if not factory.clean_tree(root):
        factory.die("factory working tree must be clean")

    title = order.title or oid
    commit_msg = f"wo-{oid}: {title} (night shift; accepted by day shift)"

    if repo.current_branch() == base:
        # The target sits on main, so the merge happens in place. The human
        # asked for this landing, and main is where it belongs.
        if repo.is_dirty():
            factory.die(f"target repo is dirty: {t_display} — commit or stash "
                        f"there first")
        merge = factory.git(repo.path, "merge", "--squash", branch, check=False)
        if merge.returncode != 0:
            print(merge.stdout + merge.stderr, file=sys.stderr)
            factory.die("squash-merge conflicts — resolve by hand in the target "
                        f"repo, or: git -C {t_display} merge --abort")
        if repo.path == root:
            # one commit on factory main: the merged code. The order file
            # is input and stays untracked.
            order.set_status("done")
            factory.git(root, "add", "-A")
            factory.git(root, "commit", "-q", "-m", commit_msg)
        else:
            # the work commits in the target repo (squash only stages it)
            factory.git(repo.path, "add", "-A")
            factory.git(repo.path, "commit", "-q", "-m", commit_msg)
            order.set_status("done")
    else:
        # The target sits on another branch. Merge in a throwaway worktree
        # at main, so the human's checkout stays exactly where it is.
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "accept"
            factory.git(repo.path, "worktree", "add", str(wt), base)
            try:
                merge = factory.git(wt, "merge", "--squash", branch, check=False)
                if merge.returncode != 0:
                    print(merge.stdout + merge.stderr, file=sys.stderr)
                    factory.die("squash-merge conflicts — merge by hand when "
                                f"ready: git -C {t_display} merge --squash {branch}")
                factory.git(wt, "add", "-A")
                factory.git(wt, "commit", "-q", "-m", commit_msg)
            finally:
                factory.git(repo.path, "worktree", "remove", "--force",
                            str(wt), check=False)
        order.set_status("done")

    print(f"accepted wo-{oid}: squash-merged {branch} into {base} in {t_display} "
          f"({ahead} commit(s)); order -> done")
    if repo.path != root:
        print(f"remember: push {t_display} yourself — the factory never pushes")
        print(f"optional cleanup: git -C {t_display} branch -D {branch}")
    else:
        print(f"optional cleanup: git branch -D {branch}")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
