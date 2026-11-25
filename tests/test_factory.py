"""Tests for the factory object model, engine adapters and locks.

Run with: uv run pytest
"""

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import factory

_nightrun_path = Path(__file__).resolve().parents[1] / "night-shift" / "run.py"
_spec = importlib.util.spec_from_file_location("nightrun", _nightrun_path)
assert _spec is not None and _spec.loader is not None
nightrun = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nightrun)

ORDER = """---
id: 001
title: Test order
status: draft
created: 2026-01-01
---

## Goal

Do the thing.

## Tasks

- Step one.

## Acceptance criteria

- It works.
"""

SYSTEM = "be brief"
PROMPT = "do it"


def make_order(tmp_path, text=ORDER, name="001-test.md"):
    path = tmp_path / name
    path.write_text(text)
    return factory.WorkOrder(path, tmp_path)


# ------------------------------------------------------- frontmatter


def test_parse_order_fields(tmp_path):
    path = tmp_path / "001-test.md"
    path.write_text(ORDER)
    fields = factory.parse_order(path)
    assert fields["id"] == "001"
    assert fields["status"] == "draft"
    assert fields["created"] == "2026-01-01"


def test_parse_order_no_frontmatter(tmp_path):
    path = tmp_path / "plain.md"
    path.write_text("# just prose\n")
    assert factory.parse_order(path) == {}


def test_parse_order_value_with_colon(tmp_path):
    path = tmp_path / "with-colon.md"
    path.write_text("---\nurl: https://example.com/a:b\n---\n")
    assert factory.parse_order(path)["url"] == "https://example.com/a:b"


def test_set_status_rewrites_frontmatter_only(tmp_path):
    order = make_order(tmp_path)
    order.path.write_text(order.path.read_text()
                          + "\n---\n\n### run\n\nstatus: done\n")
    factory.set_status(order.path, "approved")
    text = order.path.read_text()
    frontmatter = text.split("## Goal")[0]
    assert "status: approved" in frontmatter
    assert "status: done" in text  # the later look-alike stays untouched


# ---------------------------------------------------------------- lint


def test_lint_clean_order(tmp_path):
    assert make_order(tmp_path).lint() == []


def test_lint_missing_and_bad_fields(tmp_path):
    text = ORDER.replace("id: 001", "").replace("status: draft", "status: nope")
    problems = "\n".join(make_order(tmp_path, text).lint())
    assert "id: missing" in problems
    assert "status: 'nope'" in problems


def test_lint_empty_section(tmp_path):
    text = ORDER.replace("- Step one.\n", "")
    problems = make_order(tmp_path, text).lint()
    assert any("Tasks" in p for p in problems)


def test_lint_bad_created_date(tmp_path):
    text = ORDER.replace("created: 2026-01-01", "created: 01/2026")
    problems = make_order(tmp_path, text).lint()
    assert any("created" in p for p in problems)


def test_lint_branch_with_whitespace(tmp_path):
    text = ORDER.replace("---\n", "---\nbranch: wo 001\n", 1)
    problems = make_order(tmp_path, text).lint()
    assert any("branch" in p for p in problems)


def test_lint_unresolvable_repo_path(tmp_path):
    text = ORDER.replace("---\n", f"---\nrepo: {tmp_path / 'nope'}\n", 1)
    problems = make_order(tmp_path, text).lint()
    assert any("not a git repository" in p for p in problems)


def test_branch_default_and_override(tmp_path):
    assert make_order(tmp_path).branch == "wo/001"
    text = ORDER.replace("---\n", "---\nbranch: custom\n", 1)
    assert make_order(tmp_path, text).branch == "custom"


def test_append(tmp_path):
    order = make_order(tmp_path)
    order.append("\n### note\n")
    assert "### note" in order.path.read_text()


# ------------------------------------------------------------- engines


def test_engine_unknown():
    with pytest.raises(factory.FactoryError) as excinfo:
        factory.engine("bash")
    assert excinfo.value.code == 2


def test_pi_command():
    argv, ref, stdin_text = factory.engine("pi").build_command(
        SYSTEM, PROMPT, "wo-001", None)
    assert argv[0] == "pi"
    assert "--print" in argv
    assert "--approve" in argv
    assert "--mode" in argv and "json" in argv
    assert "--session-id" in argv and "wo-001" in argv
    assert PROMPT not in argv
    assert stdin_text == PROMPT
    assert ref is None


def test_pi_command_no_audit():
    argv, _, stdin_text = factory.engine("pi").build_command(
        SYSTEM, PROMPT, "wo-001", None, json_audit=False)
    assert "--mode" not in argv
    assert stdin_text == PROMPT


def test_claude_command_new_session():
    argv, ref, stdin_text = factory.engine("claude").build_command(
        SYSTEM, PROMPT, "x", None)
    assert "--resume" not in argv
    index = argv.index("--session-id")
    assert argv[index + 1] == ref
    assert PROMPT not in argv
    assert stdin_text == PROMPT


def test_claude_command_resume():
    argv, ref, stdin_text = factory.engine("claude").build_command(
        SYSTEM, PROMPT, "x", "uuid-1")
    assert "--resume" in argv and "uuid-1" in argv
    assert ref == "uuid-1"
    assert stdin_text == PROMPT


def test_opencode_command_new_session():
    argv, ref, stdin_text = factory.engine("opencode").build_command(
        SYSTEM, PROMPT, "x", None)
    assert argv[:4] == ["opencode", "run", "--auto", "--archived"]
    assert "--session" not in argv
    assert PROMPT not in argv
    assert stdin_text == f"{SYSTEM}\n\n---\n\n{PROMPT}"
    assert ref is None


def test_opencode_command_resume():
    argv, _, stdin_text = factory.engine("opencode").build_command(
        SYSTEM, PROMPT, "x", "ses_abc")
    assert argv[argv.index("--session") + 1] == "ses_abc"
    assert stdin_text == f"{SYSTEM}\n\n---\n\n{PROMPT}"


def test_opencode_ref_from_output():
    raw = "\n".join([
        '{"type":"step_start","sessionID":"ses_a"}',
        "not json",
        '{"type":"text","sessionID":"ses_b"}',
    ])
    assert factory.engine("opencode").ref_from_output(raw) == "ses_b"


def test_opencode_extract_report():
    raw = "\n".join([
        '{"type":"step_start","sessionID":"ses_a"}',
        '{"type":"text","part":{"type":"text","text":"OK"}}',
        '{"type":"step_finish"}',
    ])
    assert factory.engine("opencode").extract_report(raw) == "OK"


def test_opencode_extract_returns_raw_text():
    assert factory.engine("opencode").extract_report("hello") == "hello"


def test_pi_extract_report():
    raw = "\n".join([
        '{"type":"message_end","message":{"role":"user"}}',
        '{"type":"message_end","message":{"role":"assistant",'
        '"content":[{"type":"text","text":"done"}]}}',
    ])
    assert factory.engine("pi").extract_report(raw) == "done"


def test_pi_extract_returns_raw_text():
    assert factory.engine("pi").extract_report("plain") == "plain"


def test_claude_extract_report():
    assert factory.engine("claude").extract_report('{"result":"hi"}') == "hi"


def test_other_engines_return_no_refs():
    raw = '{"sessionID":"ses_a"}'
    assert factory.engine("pi").ref_from_output(raw) is None
    assert factory.engine("claude").ref_from_output(raw) is None


# --------------------------------------------------------------- locks


def test_lock_enter_and_release(tmp_path):
    with factory.Lock(tmp_path, "k", "repo x") as lock:
        lines = lock.path.read_text().splitlines()
        assert lines[0] == str(os.getpid())
    assert not lock.path.exists()


def test_lock_refuses_live_pid(tmp_path):
    (tmp_path / "k.lock").write_text(f"{os.getpid()}\nother\n")
    with pytest.raises(factory.FactoryError), factory.Lock(tmp_path, "k", "repo x"):
            pass


def test_lock_breaks_stale_lock(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_pid = proc.pid
    proc.wait()
    (tmp_path / "k.lock").write_text(f"{dead_pid}\ngone\n")
    with factory.Lock(tmp_path, "k", "repo x") as lock:
        assert lock.path.read_text().splitlines()[0] == str(os.getpid())


def test_lock_empty_and_fresh_is_fatal(tmp_path):
    # An empty lock younger than the grace window still stops the run.
    (tmp_path / "k.lock").write_text("")
    with pytest.raises(factory.FactoryError), factory.Lock(tmp_path, "k", "repo x"):
            pass


def test_lock_empty_and_old_is_broken(tmp_path):
    path = tmp_path / "k.lock"
    path.write_text("")
    old = time.time() - 60
    os.utime(path, (old, old))
    with factory.Lock(tmp_path, "k", "repo x") as lock:
        assert lock.path.read_text().splitlines()[0] == str(os.getpid())


# ------------------------------------------------------------ sessions


def test_session_store_roundtrip(tmp_path):
    store = factory.SessionStore(tmp_path / "sessions.json")
    store.set_ref("claude:001", "uuid-1")
    again = factory.SessionStore(tmp_path / "sessions.json")
    assert again.ref("claude:001") == "uuid-1"


# --------------------------------------------------------- target repos


def test_resolve_self(tmp_path):
    repo = factory.TargetRepo.resolve(tmp_path, "self")
    assert repo is not None
    assert repo.path == tmp_path


def test_resolve_missing_path_soft(tmp_path):
    missing = str(tmp_path / "nope")
    assert factory.TargetRepo.resolve(tmp_path, missing,
                                      update=False, soft=True) is None


def test_resolve_url_not_cloned_soft(tmp_path):
    assert factory.TargetRepo.resolve(tmp_path, "https://example.com/x.git",
                                      update=False, soft=True) is None


# -------------------------------------------------------------- helpers


def test_is_repo_url():
    assert factory.is_repo_url("https://github.com/a/b.git")
    assert factory.is_repo_url("git@github.com:a/b.git")
    assert not factory.is_repo_url("relative/path")


def test_repo_slug():
    assert factory.repo_slug(Path("/a b/c")) == "_a_b_c"


# ------------------------------------------------------- audit fixes


def test_resolve_expands_tilde(tmp_path, monkeypatch):
    real = tmp_path / "realrepo"
    subprocess.run(["git", "init", "-q", str(real)], check=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = factory.TargetRepo.resolve(tmp_path, "~/realrepo", update=False)
    assert repo is not None
    assert repo.path == (tmp_path / "realrepo").resolve()


def make_git_repo(path, branch="main"):
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "--allow-empty",
                    "-m", "init"], check=True)
    return path


def test_base_ref_guard_leaves_other_checkouts(tmp_path):
    repo_path = make_git_repo(tmp_path / "r")
    subprocess.run(["git", "-C", str(repo_path), "checkout", "-q", "-b",
                    "feature"], check=True)
    repo = factory.TargetRepo(repo_path)
    assert repo.base_ref() == "main"
    current = factory.git_out(repo_path, "branch", "--show-current")
    assert current == "feature"


def test_base_ref_on_main_without_origin(tmp_path):
    repo = factory.TargetRepo(make_git_repo(tmp_path / "r"))
    assert repo.base_ref() == "main"


def test_git_failure_raises_factory_error(tmp_path):
    with pytest.raises(factory.FactoryError) as excinfo:
        factory.git(tmp_path, "rev-parse", "--show-toplevel")
    assert "git rev-parse --show-toplevel failed" in str(excinfo.value)


def test_git_check_false_stays_quiet(tmp_path):
    r = factory.git(tmp_path, "rev-parse", "--show-toplevel", check=False)
    assert r.returncode != 0


# ------------------------------------------------ should-fix batch


def test_run_under_timeout_feeds_stdin(tmp_path):
    stub = tmp_path / "upper.py"
    stub.write_text("import sys\nsys.stdout.write(sys.stdin.read().upper())\n")
    out = tmp_path / "out"
    err = tmp_path / "err.log"
    rc = factory.run_under_timeout([sys.executable, str(stub)], tmp_path, 10,
                                   out, err, input_text="hello")
    assert rc == 0
    assert out.read_text() == "HELLO"


def test_run_under_timeout_kills_process_group(tmp_path):
    pidfile = tmp_path / "child.pid"
    stub = tmp_path / "stub.py"
    stub.write_text(
        "import subprocess\nimport time\n"
        "child = subprocess.Popen(['sleep', '60'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n")
    out = tmp_path / "out"
    err = tmp_path / "err.log"
    rc = factory.run_under_timeout([sys.executable, str(stub)], tmp_path, 1,
                                   out, err)
    assert rc == 124
    child = int(pidfile.read_text())
    for _ in range(50):
        if not factory.pid_alive(child):
            break
        time.sleep(0.1)
    assert not factory.pid_alive(child)


def test_resolve_rejects_wrong_remote(tmp_path):
    clone = tmp_path / "repos" / "other"
    clone.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "remote", "add", "origin",
                    "https://example.com/wrong.git"], check=True)
    with pytest.raises(factory.FactoryError) as excinfo:
        factory.TargetRepo.resolve(tmp_path, "https://example.com/other.git")
    assert "holds" in str(excinfo.value)


def test_resolve_rejects_wrong_remote_soft(tmp_path):
    clone = tmp_path / "repos" / "other"
    clone.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "remote", "add", "origin",
                    "https://example.com/wrong.git"], check=True)
    assert factory.TargetRepo.resolve(tmp_path, "https://example.com/other.git",
                                      soft=True) is None


def test_resolve_accepts_matching_remote(tmp_path):
    clone = tmp_path / "repos" / "other"
    clone.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "remote", "add", "origin",
                    "https://example.com/other.git"], check=True)
    repo = factory.TargetRepo.resolve(tmp_path, "https://example.com/other.git",
                                      update=False)
    assert repo is not None
    assert repo.path == clone


GOOD_APPROVED = ORDER.replace("status: draft", "status: approved")
BROKEN_APPROVED = (ORDER.replace("status: draft", "status: approved")
                   .replace("id: 001", "id: 002")
                   .replace("- Step one.\n", ""))


def test_collect_splits_healthy_from_problems(tmp_path):
    (tmp_path / "work-orders").mkdir()
    (tmp_path / "night-shift").mkdir()
    (tmp_path / "night-shift" / "NIGHT-SHIFT.md").write_text("# manual\n")
    (tmp_path / "night-shift" / "QA-SHIFT.md").write_text("# qa\n")
    (tmp_path / "work-orders" / "001-good.md").write_text(GOOD_APPROVED)
    (tmp_path / "work-orders" / "002-bad.md").write_text(BROKEN_APPROVED)
    night = nightrun.NightRun(tmp_path, "pi", None, 5, True, 60)
    healthy, problems, skipped = night.collect()
    assert [o.id for o, _ in healthy] == ["001"]
    assert [o.id for o, _ in problems] == ["002"]
    assert skipped == 0


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True,
                   capture_output=True)


def test_accept_external_merge_keeps_the_checkout(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    factory_root = make_git_repo(tmp_path / "factory")
    target = make_git_repo(tmp_path / "target")
    _git(target, "checkout", "-q", "-b", "human-branch")
    _git(target, "checkout", "-q", "-b", "wo/001", "main")
    (target / "file.txt").write_text("night work\n")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "night work")
    _git(target, "checkout", "-q", "human-branch")
    wo_dir = factory_root / "work-orders"
    wo_dir.mkdir()
    order = (f"---\nid: 001\ntitle: t\nstatus: review\ncreated: 2026-01-01\n"
             f"repo: {target}\nbranch: wo/001\n---\n\n## Goal\n\ng.\n\n"
             "## Tasks\n\n- t.\n\n## Acceptance criteria\n\n- a.\n")
    (wo_dir / "001-test.md").write_text(order)
    _git(factory_root, "add", "-A")
    _git(factory_root, "commit", "-q", "-m", "order")
    script = repo_root / "day-shift" / "accept.py"
    r = subprocess.run([sys.executable, str(script), "001"], cwd=factory_root,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    main_log = subprocess.run(
        ["git", "-C", str(target), "log", "--oneline", "main"],
        capture_output=True, text=True).stdout
    assert "wo-001" in main_log
    current = subprocess.run(
        ["git", "-C", str(target), "branch", "--show-current"],
        capture_output=True, text=True).stdout.strip()
    assert current == "human-branch"
    worktrees = subprocess.run(
        ["git", "-C", str(target), "worktree", "list"],
        capture_output=True, text=True).stdout
    assert worktrees.count("\n") == 1
