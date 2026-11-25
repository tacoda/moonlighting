"""Object model for the moonlighting factory scripts.

Classes:
    FactoryError   — a failure a human should read; CLIs exit with its message
    Engine         — host-agent adapter (PiEngine, ClaudeEngine)
    WorkOrder      — a work-order file: fields, status, lint
    TargetRepo     — a resolved target repo (the factory itself, a path, or a URL clone)
    Worktree       — a throwaway worktree of a TargetRepo (context manager)
    Lock           — a run lock file (context manager, stale-breaking)
    SessionStore   — engine session ids per order (claude engine)

Module-level helpers remain for repo plumbing: repo_root, git, git_out,
clean_tree, parse_order, set_status, die.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import NoReturn


class FactoryError(Exception):
    """A factory failure a human should read."""

    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def die(msg: str, code: int = 1) -> NoReturn:
    raise FactoryError(msg, code)


# ----------------------------------------------------------- repo plumbing


def repo_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        die("not inside a git repository")
    return Path(out)


def orders_dir(root: Path) -> Path:
    """Work orders are input, not factory source. The directory lives
    outside git by default. Point it elsewhere with FACTORY_ORDERS_DIR
    (absolute, or relative to the factory root)."""
    override = os.environ.get("FACTORY_ORDERS_DIR")
    if not override:
        return root / "work-orders"
    p = Path(override).expanduser()
    if not p.is_absolute():
        p = root / p
    return p


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=cwd, text=True,
                       capture_output=True, check=False)
    if check and r.returncode != 0:
        die(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")
    return r


def run_under_timeout(argv: list[str], cwd: Path, timeout_secs: int,
                      out_path: Path, err_path: Path,
                      input_text: str | None = None,
                      not_found_hint: str = "") -> int:
    """Run argv with output redirected to out_path and err_path. Feed
    input_text on stdin. On timeout, kill the whole process group, so
    engine children cannot outlive the run. Returns the exit code, 124 on
    timeout."""
    try:
        with out_path.open("w") as out, err_path.open("w") as err:
            proc = subprocess.Popen(
                argv, cwd=cwd, stdout=out, stderr=err,
                stdin=(subprocess.PIPE if input_text is not None
                       else subprocess.DEVNULL),
                start_new_session=True)
            try:
                proc.communicate(
                    input_text.encode() if input_text is not None else None,
                    timeout=timeout_secs)
                return proc.returncode
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait()
                return 124
    except FileNotFoundError:
        die(f"engine executable not found: {argv[0]} {not_found_hint}".strip(),
            127)


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
    """Rewrite the status line, but only inside the frontmatter. Body
    horizontal rules never reopen the frontmatter."""
    lines = path.read_text().splitlines()
    fence_count = 0
    in_fm = False
    for i, line in enumerate(lines):
        if line.strip() == "---":
            fence_count += 1
            in_fm = fence_count == 1
            continue
        if in_fm and line.startswith("status:"):
            lines[i] = f"status: {new_status}"
            break
    path.write_text("\n".join(lines) + "\n")


VALID_STATUS = ("draft", "approved", "review", "blocked", "done", "rejected")
REQUIRED_SECTIONS = ("## Goal", "## Tasks", "## Acceptance criteria")


def is_repo_url(value: str) -> bool:
    return "://" in value or value.startswith("git@")


def repo_slug(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(path))


# ---------------------------------------------------------------- engines


class Engine:
    """Adapter for one host agent. Subclasses know how to run headless and
    how to read the final report back out of a raw JSON capture."""

    name: str = ""
    default_binary: str = ""

    def __init__(self, binary: str | None = None):
        self.binary = binary or os.environ.get(
            f"{self.name.upper()}_BIN", self.default_binary)

    def build_command(
        self, system_prompt: str, prompt: str, session_id: str,
        session_ref: str | None, json_audit: bool = True,
        model: str | None = None,
    ) -> tuple[list[str], str | None, str | None]:
        """Headless argv for one pass. session_id is the engine-side session
        handle; session_ref resumes a known session (claude). json_audit
        switches the raw event capture on. The prompt rides on stdin, never
        on argv: order files grow every cycle, and Linux caps one argv item
        at 128 KiB. model passes a host-specific model string verbatim;
        None keeps the host default. Returns (argv, ref_to_remember,
        stdin_text)."""
        raise NotImplementedError

    def extract_report(self, raw: str) -> str:
        """Final assistant text from a raw capture; raw text as fallback."""
        raise NotImplementedError

    def ref_from_output(self, raw: str) -> str | None:
        """Session ref recovered from a finished pass; None by default.
        Engines whose host picks the session id (opencode) override this."""
        return None


class PiEngine(Engine):
    name = "pi"
    default_binary = "pi"

    def build_command(self, system_prompt, prompt, session_id,
                      session_ref, json_audit=True, model=None):
        argv = [self.binary, "--print", "--approve",
                "--append-system-prompt", system_prompt,
                "--session-id", session_id]
        if json_audit:
            argv += ["--mode", "json"]
        if model:
            argv += ["--model", model]
        return argv, None, prompt

    def extract_report(self, raw: str) -> str:
        last = None
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
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


class ClaudeEngine(Engine):
    name = "claude"
    default_binary = "claude"

    def build_command(self, system_prompt, prompt, session_id,
                      session_ref, json_audit=True, model=None):
        argv = [self.binary, "--print", "--dangerously-skip-permissions",
                "--append-system-prompt", system_prompt]
        if json_audit:
            argv += ["--output-format", "json"]
        if session_ref:
            argv += ["--resume", session_ref]
        else:
            session_ref = str(uuid.uuid4())
            argv += ["--session-id", session_ref]
        if model:
            argv += ["--model", model]
        return argv, session_ref, prompt

    def extract_report(self, raw: str) -> str:
        try:
            text = json.loads(raw).get("result")
            if isinstance(text, str) and text.strip():
                return text
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
        return raw


class OpenCodeEngine(Engine):
    name = "opencode"
    default_binary = "opencode"

    def build_command(self, system_prompt, prompt, session_id,
                      session_ref, json_audit=True, model=None):
        argv = [self.binary, "run", "--auto", "--archived"]
        if json_audit:
            argv += ["--format", "json"]
        if session_ref:
            argv += ["--session", session_ref]
        if model:
            argv += ["--model", model]
        # opencode has no --append-system-prompt: the manual rides in the message
        return argv, None, f"{system_prompt}\n\n---\n\n{prompt}"

    def ref_from_output(self, raw: str) -> str | None:
        # every JSON event carries the host-chosen sessionID (ses_...)
        ref = None
        for line in raw.splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = rec.get("sessionID")
            if isinstance(sid, str) and sid.startswith("ses"):
                ref = sid
        return ref

    def extract_report(self, raw: str) -> str:
        texts = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "text":
                text = (rec.get("part") or {}).get("text")
                if isinstance(text, str):
                    texts.append(text)
        text = "".join(texts).strip()
        return text or raw


ENGINES = {"pi": PiEngine, "claude": ClaudeEngine, "opencode": OpenCodeEngine}


def engine(name: str) -> Engine:
    cls = ENGINES.get(name)
    if cls is None:
        die(f"unknown engine: {name} (supported: {', '.join(ENGINES)})", 2)
    return cls()


# ------------------------------------------------------------- work orders


class WorkOrder:
    """One work-order markdown file: fields, status transitions, lint."""

    def __init__(self, path: Path, root: Path):
        self.path = path
        self.root = root
        self.fields = parse_order(path)

    @property
    def rel(self) -> str:
        try:
            return str(self.path.relative_to(self.root))
        except ValueError:
            return self.path.name

    @property
    def id(self) -> str:
        return self.fields.get("id", "")

    @property
    def title(self) -> str:
        return self.fields.get("title", "")

    @property
    def status(self) -> str:
        return self.fields.get("status", "")

    @property
    def branch(self) -> str:
        return self.fields.get("branch") or f"wo/{self.id}"

    @property
    def repo_value(self) -> str:
        return self.fields.get("repo", "")

    @property
    def model(self) -> str:
        return self.fields.get("model", "")

    def set_status(self, new_status: str) -> None:
        set_status(self.path, new_status)
        self.fields["status"] = new_status

    def append(self, text: str) -> None:
        with self.path.open("a") as f:
            f.write(text)

    def record_decision(self, text: str) -> None:
        stamp = f"{datetime.now():%Y-%m-%d %H:%M}"
        self.append(f"\n### {stamp} — day shift decision\n\n{text}\n")

    def lint(self) -> list[str]:
        """Mechanical validation. Returns problems (empty = clean).
        Catches what would waste a night; judgment calls are not lint's
        business."""
        problems: list[str] = []
        if not self.fields:
            return [f"{self.rel}: no readable frontmatter (--- block)"]
        oid = self.id
        if not oid:
            problems.append("id: missing")
        elif not re.fullmatch(r"[0-9a-f]{7}", oid):
            problems.append(f"id: '{oid}' is not a 7-char hex sha")
        if oid and not self.path.stem.startswith(oid):
            problems.append(f"id '{oid}' does not match the filename prefix "
                            f"'{self.path.stem[:len(oid)]}'")
        if not self.title:
            problems.append("title: missing")
        if not self.status:
            problems.append("status: missing")
        elif self.status not in VALID_STATUS:
            problems.append(f"status: '{self.status}' is not one of "
                            f"{', '.join(VALID_STATUS)}")
        created = self.fields.get("created", "")
        if not created:
            problems.append("created: missing")
        else:
            try:
                date.fromisoformat(created)
            except ValueError:
                problems.append(f"created: '{created}' is not YYYY-MM-DD")
        branch = self.fields.get("branch")
        if branch and re.search(r"\s", branch):
            problems.append(f"branch: '{branch}' contains whitespace")
        model = self.model
        if model and re.search(r"\s", model):
            problems.append(f"model: '{model}' contains whitespace")
        repo = self.repo_value
        if (repo and repo != "self" and not is_repo_url(repo)
                and TargetRepo.resolve(self.root, repo, update=False,
                                       soft=True) is None):
            problems.append(f"repo: '{repo}' is not a git repository")

        body: dict[str, list[str]] = {}
        current = None
        for line in self.path.read_text().splitlines():
            if line.startswith("## "):
                current = line[3:].strip()
                body.setdefault(current, [])
                continue
            if current:
                body[current].append(line)
        for sec in REQUIRED_SECTIONS:
            name = sec[3:]
            if not [line for line in body.get(name, []) if line.strip()]:
                problems.append(f"section '{name}': missing or empty")

        return [f"{self.rel}: {p}" for p in problems]


# ----------------------------------------------------------- target repos


class TargetRepo:
    """A resolved target repository: the factory itself, a local path, or a
    URL clone living under <factory>/repos/."""

    def __init__(self, path: Path, root: Path | None = None):
        self.path = path
        self.root = root or path

    @classmethod
    def resolve(cls, root: Path, repo_value: str | None,
                update: bool = True, soft: bool = False) -> TargetRepo | None:
        """Resolve an order's `repo:` field. None/"self" -> the factory; a
        path -> that working tree; a git URL -> cloned under repos/ and
        refreshed (update=True). soft=True returns None instead of failing."""
        if not repo_value or repo_value == "self":
            return cls(root, root)
        repos_dir = root / "repos"
        if is_repo_url(repo_value):
            name = repo_value.rstrip("/").split("/")[-1].removesuffix(".git")
            target = repos_dir / name
            if target.exists():
                wanted = repo_value.rstrip("/").removesuffix(".git")
                r = git(root, "-C", str(target), "remote", "get-url",
                        "origin", check=False)
                remote = r.stdout.strip().rstrip("/").removesuffix(".git")
                if remote != wanted:
                    msg = (f"repos/{name} holds '{remote or 'no origin remote'}', "
                           f"not {repo_value} — remove or rename the directory")
                    if soft:
                        return None
                    die(msg)
                if update:
                    git(root, "-C", str(target),
                        "fetch", "--quiet", "--all", "--prune")
                return cls(target, root)
            if not update:
                return None
            repos_dir.mkdir(parents=True, exist_ok=True)
            print(f"cloning {repo_value} -> repos/{name}")
            r = git(root, "clone", "--quiet", repo_value, str(target), check=False)
            if r.returncode != 0:
                if soft:
                    return None
                die(f"clone failed: {r.stderr.strip()}")
            return cls(target, root)
        p = Path(repo_value).expanduser()
        if not p.is_absolute():
            p = root / p
        p = p.resolve()
        if subprocess.run(["git", "-C", str(p), "rev-parse", "--git-dir"],
                          capture_output=True).returncode != 0:
            if soft:
                return None
            die(f"repo is not a git repository: {p}")
        return cls(p, root)

    def display(self) -> str:
        if self.path == self.root:
            return "this factory"
        try:
            return str(self.path.relative_to(self.root))
        except ValueError:
            return str(self.path)

    def slug(self) -> str:
        return repo_slug(self.path)

    def is_dirty(self) -> bool:
        return git_out(self.path, "status", "--porcelain") != ""

    def current_branch(self) -> str:
        return git_out(self.path, "branch", "--show-current")

    def local_main(self) -> str:
        for ref in ("main", "master"):
            if git(self.path, "show-ref", "--verify", "--quiet",
                   f"refs/heads/{ref}", check=False).returncode == 0:
                return ref
        return self.current_branch() or "main"

    def base_ref(self) -> str:
        """Night branches start from local main, fast-forwarded to the remote
        default when possible: accepted-but-unpushed work makes local main the
        freshest truth, and ff-only never rewrites anything. The ff updates
        the working tree, so it runs only when main is checked out."""
        main = self.local_main()
        if self.current_branch() != main:
            return main
        r = git(self.path, "symbolic-ref", "--quiet", "--short",
                "refs/remotes/origin/HEAD", check=False)
        if r.returncode == 0 and r.stdout.strip():
            git(self.path, "merge", "--quiet", "--ff-only", r.stdout.strip(),
                check=False)
        return main

    def branch_exists(self, name: str) -> bool:
        return git(self.path, "show-ref", "--verify", "--quiet",
                   f"refs/heads/{name}", check=False).returncode == 0

    def prune_worktrees(self) -> None:
        git(self.path, "worktree", "prune")


class Worktree:
    """Throwaway worktree of a TargetRepo, on one branch. Disposable: removal
    on exit, the branch keeps everything."""

    def __init__(self, repo: TargetRepo, path: Path, branch: str, base: str):
        self.repo = repo
        self.path = path
        self.branch = branch
        self.base = base

    def __enter__(self) -> Worktree:
        self.repo.prune_worktrees()
        if self.path.exists():
            die(f"worktree path already exists: {self.path} — remove it "
                f"before rerunning this order")
        if self.repo.branch_exists(self.branch):
            git(self.repo.path, "worktree", "add", str(self.path), self.branch)
            print(f"resuming branch {self.branch} in a worktree")
        else:
            git(self.repo.path, "worktree", "add", "-b", self.branch,
                str(self.path), self.base)
            print(f"new branch {self.branch} (from {self.base}) in a worktree")
        return self

    def __exit__(self, *exc) -> None:
        # --force: ignored artifacts (node_modules etc.) are not source
        r = git(self.repo.path, "worktree", "remove", str(self.path), check=False)
        if r.returncode != 0:
            git(self.repo.path, "worktree", "remove", "--force", str(self.path))


# ---------------------------------------------------------------- locks


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class Lock:
    """Run lock file. One night per target repo, one per factory checkout.
    Locks left by dead processes are broken automatically."""

    def __init__(self, locks_dir: Path, key: str, what: str):
        locks_dir.mkdir(parents=True, exist_ok=True)
        self.path = locks_dir / f"{key}.lock"
        self.what = what

    def acquire(self) -> Lock:
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                first = self.path.read_text().split("\n")[0].strip()
                if not first:
                    # No pid recorded yet. An empty lock turns stale after a
                    # grace window. The window protects a runner caught
                    # between file create and pid write.
                    if time.time() - self.path.stat().st_mtime > 5:
                        print(f"breaking stale lock: {self.path.name} "
                              f"(no pid recorded)")
                        self.path.unlink()
                        continue
                elif first.isdigit() and not pid_alive(int(first)):
                    print(f"breaking stale lock: {self.path.name} "
                          f"(pid {first} is gone)")
                    self.path.unlink()
                    continue
                die(f"{self.what} is being worked by pid {first or '?'} — run "
                    f"one factory per repo (see docs/runbook.md)")
            os.write(fd, f"{os.getpid()}\n{self.what}\n".encode())
            os.close(fd)
            return self

    def release(self) -> None:
        self.path.unlink(missing_ok=True)

    def __enter__(self) -> Lock:
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


# --------------------------------------------------------------- sessions


class SessionStore:
    """Engine session ids per order, so reruns continue the same
    conversation. pi tracks ids on its own; claude needs us to keep them."""

    def __init__(self, path: Path):
        self.path = path
        self._data: dict = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text())
            except json.JSONDecodeError as e:
                die(f"corrupt session store: {path} ({e}) — fix or delete "
                    f"the file before rerunning", 1)

    def ref(self, key: str) -> str | None:
        return self._data.get(key)

    def set_ref(self, key: str, ref: str) -> None:
        self._data[key] = ref
        # atomic write: a kill mid-write must not truncate the store
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=1, sort_keys=True) + "\n")
        tmp.replace(self.path)
