"""Shared helpers for the moonlighting factory scripts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def repo_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        die("not inside a git repository")
    return Path(out)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=check
    )


def git_out(cwd: Path, *args: str) -> str:
    return git(cwd, *args).stdout.strip()


def clean_tree(cwd: Path) -> bool:
    return git_out(cwd, "status", "--porcelain") == ""


def parse_order(path: Path) -> dict[str, str]:
    """Parse the YAML-ish frontmatter of a work order (key: value lines)."""
    fields: dict[str, str] = {}
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return fields
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def set_status(path: Path, new_status: str) -> None:
    """Rewrite the status line — but only inside the frontmatter."""
    lines = path.read_text().splitlines()
    in_fm = False
    for i, line in enumerate(lines):
        if line.strip() == "---":
            in_fm = not in_fm
            continue
        if in_fm and line.startswith("status:"):
            lines[i] = f"status: {new_status}"
            break
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------- engines


def engine_bin(engine: str) -> str:
    default = {"pi": "pi", "claude": "claude"}.get(engine)
    if default is None:
        die(f"unknown engine: {engine} (supported: pi, claude)", 2)
    return os.environ.get(f"{engine.upper()}_BIN", default)


def build_command(
    engine: str, binary: str, system_prompt: str, prompt: str,
    order_id: str, session_ref: str | None,
) -> tuple[list[str], str | None]:
    """Build the headless command for a host agent.

    Returns (argv, session_ref_to_remember). pi tracks sessions by a
    deterministic id on its own; claude needs a uuid we keep per order.
    """
    if engine == "pi":
        return ([binary, "--print", "--approve",
                 "--append-system-prompt", system_prompt,
                 "--session-id", f"wo-{order_id}",
                 prompt], None)
    if engine == "claude":
        argv = [binary, "--print", "--dangerously-skip-permissions",
                "--append-system-prompt", system_prompt]
        if session_ref:
            argv += ["--resume", session_ref]
        else:
            session_ref = str(uuid.uuid4())
            argv += ["--session-id", session_ref]
        return argv + [prompt], session_ref
    die(f"unknown engine: {engine}", 2)


def load_sessions(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_sessions(path: Path, sessions: dict) -> None:
    path.write_text(json.dumps(sessions, indent=1, sort_keys=True) + "\n")


# ------------------------------------------------------------ target repos


def is_repo_url(value: str) -> bool:
    return "://" in value or value.startswith("git@")


def repo_slug(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(path))


def display_target(root: Path, target: Path) -> str:
    if target == root:
        return "this factory"
    return str(target.relative_to(root)) if target.is_relative_to(root) else str(target)


def resolve_target(
    root: Path, repo_value: str | None, update: bool = True, soft: bool = False,
) -> Path | None:
    """Resolve an order's `repo:` field to a git working tree.

    None or "self"  -> the factory repo itself
    path            -> that working tree (absolute, or relative to the factory)
    git URL         -> cloned/updated under <factory>/repos/<name>/

    update=False skips network (status reports); soft=True returns None
    instead of dying when the repo is missing or not cloned yet.
    """
    if not repo_value or repo_value == "self":
        return root
    repos_dir = root / "repos"
    if is_repo_url(repo_value):
        name = repo_value.rstrip("/").split("/")[-1].removesuffix(".git")
        target = repos_dir / name
        if target.exists():
            if update:
                git(root, "-C", str(target), "fetch", "--quiet", "--all", "--prune")
            return target
        if not update:
            return None
        repos_dir.mkdir(parents=True, exist_ok=True)
        print(f"cloning {repo_value} -> repos/{name}")
        r = git(root, "clone", "--quiet", repo_value, str(target), check=False)
        if r.returncode != 0:
            if soft:
                return None
            die(f"clone failed: {r.stderr.strip()}")
        return target
    p = Path(repo_value)
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if subprocess.run(["git", "-C", str(p), "rev-parse", "--git-dir"],
                      capture_output=True).returncode != 0:
        if soft:
            return None
        die(f"repo is not a git repository: {p}")
    return p


def local_main(target: Path) -> str:
    """The local branch day-shift merges land on."""
    for ref in ("main", "master"):
        if git(target, "show-ref", "--verify", "--quiet",
               f"refs/heads/{ref}", check=False).returncode == 0:
            return ref
    return git_out(target, "branch", "--show-current") or "main"


def base_ref(target: Path) -> str:
    """Where night branches start: the remote default if there is one, else local main."""
    r = git(target, "symbolic-ref", "--quiet", "--short",
            "refs/remotes/origin/HEAD", check=False)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return local_main(target)


# ------------------------------------------------------------------ locks


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(locks_dir: Path, key: str, what: str) -> Path:
    locks_dir.mkdir(parents=True, exist_ok=True)
    path = locks_dir / f"{key}.lock"
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            first = path.read_text().split("\n")[0].strip()
            if first.isdigit() and not pid_alive(int(first)):
                print(f"breaking stale lock: {path.name} (pid {first} is gone)")
                path.unlink()
                continue
            die(f"{what} is being worked by pid {first or '?'} — run one factory "
                f"per repo (see docs/runbook.md)")
        os.write(fd, f"{os.getpid()}\n{what}\n".encode())
        os.close(fd)
        return path


def release_lock(path: Path) -> None:
    path.unlink(missing_ok=True)
