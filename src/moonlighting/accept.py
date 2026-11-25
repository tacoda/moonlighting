"""moonlighting accept ID — push the order branch and open a PR.

The day shift never merges locally. Accept pushes the review branch to
origin, opens a GitHub PR, records its URL in the order, and leaves the
merge to you.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

from . import factory


def gh(args: list[str],
       env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run the gh CLI under the repo profile's identity via GH_TOKEN."""
    full_env = {**os.environ, **env} if env else None
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True,
                              env=full_env)
    except FileNotFoundError:
        factory.die("gh not found — install the GitHub CLI to open PRs")


def github_slug(url: str) -> str | None:
    """owner/name from a remote URL. Works for https, ssh and ssh host
    aliases: everything before the last two segments is host noise."""
    cleaned = url.rstrip("/").removesuffix(".git")
    parts = re.split(r"[:/]", cleaned)
    if len(parts) < 2:
        return None
    return "/".join(parts[-2:])


def pr_body(order: factory.WorkOrder) -> str:
    """The order content up to the first runner log section, minus the
    frontmatter."""
    text = order.path.read_text()
    cut = text.find("\n### ")
    body = text[:cut] if cut >= 0 else text
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end >= 0:
            body = body[end + 5:]
    return body.strip()


def main() -> None:
    if len(sys.argv) != 2:
        factory.die("usage: moonlighting accept ID", 2)
    oid = sys.argv[1]

    fl = factory.floor()
    matches = sorted(fl["orders"].glob(f"{oid}*.md"))
    if len(matches) != 1:
        factory.die(f"expected exactly one order matching '{oid}*', "
                    f"found {len(matches)}")
    order = factory.WorkOrder(matches[0])
    if order.status != "review":
        factory.die(f"{order.id} is '{order.status}', not 'review' — "
                    f"accept ships review orders")
    repo = factory.TargetRepo.resolve(order.repo_value)
    assert repo is not None
    branch = order.branch
    t_display = repo.display()

    if not repo.branch_exists(branch):
        factory.die(f"branch {branch} does not exist in {t_display}")
    base = repo.local_main()
    ahead = int(factory.git_out(repo.path, "rev-list", "--count",
                                f"{base}..{branch}") or "0")
    if ahead == 0:
        factory.die(f"{branch} has no commits ahead of {base} in {t_display}"
                    f" — nothing to ship")

    origin = factory.git_out(repo.path, "remote", "get-url", "origin")
    slug = github_slug(origin)
    if not slug:
        factory.die(f"could not read owner/name from the origin of "
                    f"{t_display}: {origin}")

    env = repo.env()
    factory.git(repo.path, "push", "origin", branch, env=env)

    title = order.title or oid
    pr = gh(["pr", "create", "--repo", slug, "--base", base,
             "--head", branch,
             "--title", f"wo-{oid}: {title}",
             "--body", pr_body(order)], env=env)
    if pr.returncode != 0 and "already exists" in pr.stderr:
        pr = gh(["pr", "view", branch, "--repo", slug,
                 "--json", "url", "-q", ".url"], env=env)
    if pr.returncode != 0:
        print(pr.stderr.strip())
        factory.die("gh failed after the push — open the PR by hand")
    pr_url = pr.stdout.strip() or "(see GitHub)"

    order.record_decision(f"PR opened: {pr_url}")
    print(f"shipped wo-{oid}: pushed {branch}, PR {pr_url}")
    print("merge it on GitHub, then clean up: "
          f"moonlighting remove {oid} --yes")


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
