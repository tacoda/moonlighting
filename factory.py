"""Shared helpers for the moonlighting factory scripts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import date
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


VALID_STATUS = ("draft", "approved", "review", "blocked", "done", "rejected")
REQUIRED_SECTIONS = ("## Goal", "## Tasks", "## Acceptance criteria")


def lint_order(path: Path, root: Path) -> list[str]:
    """Mechanical work-order validation. Returns problems (empty = clean).

    Catches everything that would waste a night: unreadable frontmatter,
    missing or malformed fields, empty required sections, repo paths that
    don't resolve. Judgment calls are not lint's business.
    """
    problems: list[str] = []
    fields = parse_order(path)
    if not fields:
        return [f"{path.name}: no readable frontmatter (--- block)"]
    rel = str(path.relative_to(root)) if path.is_relative_to(root) else path.name

    oid = fields.get("id", "")
    if not oid:
        problems.append("id: missing")
    elif not re.fullmatch(r"\d{3}", oid):
        problems.append(f"id: '{oid}' is not 3 digits (zero-pad, e.g. 007)")
    if not fields.get("title"):
        problems.append("title: missing")
    status = fields.get("status", "")
    if not status:
        problems.append("status: missing")
    elif status not in VALID_STATUS:
        problems.append(f"status: '{status}' is not one of {', '.join(VALID_STATUS)}")
    created = fields.get("created", "")
    if not created:
        problems.append("created: missing")
    else:
        try:
            date.fromisoformat(created)
        except ValueError:
            problems.append(f"created: '{created}' is not YYYY-MM-DD")
    branch = fields.get("branch")
    if branch and re.search(r"\s", branch):
        problems.append(f"branch: '{branch}' contains whitespace")
    repo = fields.get("repo")
    if repo and repo != "self" and not is_repo_url(repo):
        if resolve_target(root, repo, update=False, soft=True) is None:
            problems.append(f"repo: '{repo}' is not a git repository")

    body: dict[str, list[str]] = {}
    current = None
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            body.setdefault(current, [])
            continue
        if current:
            body[current].append(line)
    for sec in REQUIRED_SECTIONS:
        name = sec[3:]
        if not [l for l in body.get(name, []) if l.strip()]:
            problems.append(f"section '{name}': missing or empty")

    return [f"{rel}: {p}" for p in problems]


# ---------------------------------------------------------------- engines


def engine_bin(engine: str) -> str:
    default = {"pi": "pi", "claude": "claude"}.get(engine)
    if default is None:
        die(f"unknown engine: {engine} (supported: pi, claude)", 2)
    return os.environ.get(f"{engine.upper()}_BIN", default)


def build_command(
    engine: str, binary: str, system_prompt: str, prompt: str,
    session_id: str, session_ref: str | None, json_audit: bool = True,
) -> tuple[list[str], str | None]:
    """Build the headless command for a host agent.

    session_id is the engine-side session handle for this run (pi: a
    deterministic id; claude: a uuid we keep per order — pass session_ref to
    resume). json_audit switches the raw JSON event capture on; run.py then
    extracts the final text with extract_report().

    Returns (argv, session_ref_to_remember).
    """
    if engine == "pi":
        argv = [binary, "--print", "--approve",
                "--append-system-prompt", system_prompt,
                "--session-id", session_id]
        if json_audit:
            argv += ["--mode", "json"]
        return argv + [prompt], None
    if engine == "claude":
        argv = [binary, "--print", "--dangerously-skip-permissions",
                "--append-system-prompt", system_prompt]
        if json_audit:
            argv += ["--output-format", "json"]
        if session_ref:
            argv += ["--resume", session_ref]
        else:
            session_ref = str(uuid.uuid4())
            argv += ["--session-id", session_ref]
        return argv + [prompt], session_ref
    die(f"unknown engine: {engine}", 2)


def extract_report(engine: str, raw: str) -> str:
    """Final assistant text from a JSON-audit capture; raw text as fallback."""
    try:
        if engine == "pi":
            last = None
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("type") == "message_end":
                    msg = rec.get("message") or {}
                    if msg.get("role") == "assistant":
                        last = msg
            if last is None:
                return raw
            blocks = last.get("content")
            if isinstance(blocks, list):
                text = "".join(b.get("text", "") for b in blocks
                               if isinstance(b, dict) and b.get("type") == "text")
                return text.strip() or raw
            if isinstance(blocks, str) and blocks.strip():
                return blocks.strip()
            return raw
        if engine == "claude":
            obj = json.loads(raw)
            text = obj.get("result")
            if isinstance(text, str) and text.strip():
                return text
    except (json.JSONDecodeError, ValueError, AttributeError):
        pass
    return raw


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


def base_ref(root: Path, target: Path) -> str:
    """Where night branches start: the target's local main, fast-forwarded to
    the remote default when possible. Accepted-but-unpushed work makes local
    main the freshest truth; ff-only never rewrites anything."""
    main = local_main(target)
    r = git(target, "symbolic-ref", "--quiet", "--short",
            "refs/remotes/origin/HEAD", check=False)
    if r.returncode == 0 and r.stdout.strip():
        git(target, "merge", "--quiet", "--ff-only", r.stdout.strip(), check=False)
    return main


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
