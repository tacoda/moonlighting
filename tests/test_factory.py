"""Tests for the factory object model, engine adapters and locks.

Run with: uv run pytest
"""

import gzip
import os
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest

from moonlighting import factory
from moonlighting import run as nightrun

ORDER = """---
id: a1b2c3d
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


def make_order(tmp_path, text=ORDER, name="a1b2c3d-test.md"):
    path = tmp_path / name
    path.write_text(text)
    return factory.WorkOrder(path, tmp_path)


# ------------------------------------------------------- frontmatter


def test_parse_order_fields(tmp_path):
    path = tmp_path / "a1b2c3d-test.md"
    path.write_text(ORDER)
    fields = factory.parse_order(path)
    assert fields["id"] == "a1b2c3d"
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
    text = ORDER.replace("id: a1b2c3d", "").replace("status: draft", "status: nope")
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
    assert make_order(tmp_path).branch == "wo/a1b2c3d"
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
        SYSTEM, PROMPT, "wo-001", None, model="x/y:high")
    assert argv[0] == "pi"
    assert "--print" in argv
    assert "--approve" in argv
    assert "--mode" in argv and "json" in argv
    assert "--session-id" in argv and "wo-001" in argv
    assert "--model" in argv and "x/y:high" in argv
    assert PROMPT not in argv
    assert stdin_text == PROMPT
    assert ref is None


def test_pi_command_no_audit():
    argv, _, stdin_text = factory.engine("pi").build_command(
        SYSTEM, PROMPT, "wo-001", None, json_audit=False)
    assert "--mode" not in argv
    assert "--model" not in argv
    assert stdin_text == PROMPT


def test_claude_command_new_session():
    argv, ref, stdin_text = factory.engine("claude").build_command(
        SYSTEM, PROMPT, "x", None, model="alias-1")
    assert "--resume" not in argv
    index = argv.index("--session-id")
    assert argv[index + 1] == ref
    assert "--model" in argv and "alias-1" in argv
    assert PROMPT not in argv
    assert stdin_text == PROMPT


def test_claude_command_resume():
    argv, ref, stdin_text = factory.engine("claude").build_command(
        SYSTEM, PROMPT, "x", "uuid-1")
    assert "--resume" in argv and "uuid-1" in argv
    assert ref == "uuid-1"
    assert "--model" not in argv
    assert stdin_text == PROMPT


def test_opencode_command_new_session():
    argv, ref, stdin_text = factory.engine("opencode").build_command(
        SYSTEM, PROMPT, "x", None, model="a/b#c")
    assert argv[:4] == ["opencode", "run", "--auto", "--archived"]
    assert "--session" not in argv
    assert "--model" in argv and "a/b#c" in argv
    assert PROMPT not in argv
    assert stdin_text == f"{SYSTEM}\n\n---\n\n{PROMPT}"
    assert ref is None


def test_opencode_command_resume():
    argv, _, stdin_text = factory.engine("opencode").build_command(
        SYSTEM, PROMPT, "x", "ses_abc")
    assert argv[argv.index("--session") + 1] == "ses_abc"
    assert "--model" not in argv
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
                   .replace("id: a1b2c3d", "id: b2c3d4e")
                   .replace("- Step one.\n", ""))


def test_collect_splits_healthy_from_problems(tmp_path):
    (tmp_path / "work-orders").mkdir()
    (tmp_path / "night-shift").mkdir()
    (tmp_path / "night-shift" / "NIGHT-SHIFT.md").write_text("# manual\n")
    (tmp_path / "night-shift" / "QA-SHIFT.md").write_text("# qa\n")
    (tmp_path / "work-orders" / "a1b2c3d-good.md").write_text(GOOD_APPROVED)
    (tmp_path / "work-orders" / "b2c3d4e-bad.md").write_text(BROKEN_APPROVED)
    night = nightrun.NightRun(tmp_path, "pi", None, 5, True, 60)
    healthy, problems, skipped = night.collect()
    assert [o.id for o, _ in healthy] == ["a1b2c3d"]
    assert [o.id for o, _ in problems] == ["b2c3d4e"]
    assert skipped == 0


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True,
                   capture_output=True)


def test_accept_external_merge_keeps_the_checkout(tmp_path):
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
    r = subprocess.run([sys.executable, "-m", "moonlighting.accept", "001"],
                       cwd=factory_root, capture_output=True, text=True)
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


def test_lint_id_filename_mismatch(tmp_path):
    order = make_order(tmp_path, name="007-mismatch.md")
    problems = order.lint()
    assert any("does not match the filename prefix" in p for p in problems)


def test_run_empty_filter_lists_other_repos(tmp_path, capsys):
    shop = make_git_repo(tmp_path / "shop")
    other = make_git_repo(tmp_path / "other")
    (tmp_path / "work-orders").mkdir()
    (tmp_path / "night-shift").mkdir()
    (tmp_path / "night-shift" / "NIGHT-SHIFT.md").write_text("# manual\n")
    (tmp_path / "night-shift" / "QA-SHIFT.md").write_text("# qa\n")
    order = GOOD_APPROVED.replace("---\n", f"---\nrepo: {shop}\n", 1)
    (tmp_path / "work-orders" / "a1b2c3d-shop.md").write_text(order)
    night = nightrun.NightRun(tmp_path, "pi", str(other), 5, True, 60)
    night.run()
    out = capsys.readouterr().out
    assert "nothing approved for this repo" in out
    assert "approved orders exist for other repos" in out
    assert "a1b2c3d" in out and str(shop) in out


def test_preflight_failure_lands_in_errors_log(tmp_path):
    floor = make_git_repo(tmp_path / "floor")
    r = subprocess.run([sys.executable, "-m", "moonlighting.run"], cwd=floor,
                       capture_output=True, text=True)
    assert r.returncode == 1
    log = floor / "night-shift" / "logs" / "errors.log"
    assert "work orders directory" in log.read_text()


def test_workorder_model_field(tmp_path):
    text = ORDER.replace("---\n", "---\nmodel: anthropic/claude-opus-5\n", 1)
    order = make_order(tmp_path, text)
    assert order.model == "anthropic/claude-opus-5"
    assert make_order(tmp_path).model == ""


def test_lint_rejects_model_with_whitespace(tmp_path):
    text = ORDER.replace("---\n", "---\nmodel: claude opus\n", 1)
    problems = make_order(tmp_path, text).lint()
    assert any("model" in p for p in problems)


def test_lint_rejects_bad_id_format(tmp_path):
    text = ORDER.replace("id: a1b2c3d", "id: zebra-12")
    problems = make_order(tmp_path, text).lint()
    assert any("7-char hex sha" in p for p in problems)


def test_new_order_approve_flag(tmp_path):
    root = make_git_repo(tmp_path / "f")
    (root / "work-orders").mkdir()
    docs = root / "docs"
    docs.mkdir()
    template = Path(__file__).resolve().parents[1] / "docs" / "work-order-template.md"
    (docs / "work-order-template.md").write_text(template.read_text())
    r = subprocess.run([sys.executable, "-m", "moonlighting.new_order",
                        "Quick", "--approve"],
                       cwd=root, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    created = list((root / "work-orders").glob("*-quick.md"))
    assert len(created) == 1
    sha = created[0].name.split("-")[0]
    assert re.fullmatch(r"[0-9a-f]{7}", sha)
    text = created[0].read_text()
    assert "status: approved" in text
    assert "the night picks it up" in r.stdout


def test_new_order_requires_title_when_not_interactive(tmp_path):
    root = make_git_repo(tmp_path / "f")
    r = subprocess.run([sys.executable, "-m", "moonlighting.new_order"], cwd=root,
                       capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 2
    assert "not running interactively" in r.stderr


def test_orders_dir_env_override(tmp_path, monkeypatch):
    assert factory.orders_dir(tmp_path) == tmp_path / "work-orders"
    monkeypatch.setenv("FACTORY_ORDERS_DIR", str(tmp_path / "inbox"))
    assert factory.orders_dir(tmp_path) == tmp_path / "inbox"
    monkeypatch.setenv("FACTORY_ORDERS_DIR", "inbox2")
    assert factory.orders_dir(tmp_path) == tmp_path / "inbox2"


def test_night_timeout_guard(tmp_path):
    floor = make_git_repo(tmp_path / "floor")
    env = dict(os.environ, NIGHT_TIMEOUT_SECS="abc")
    r = subprocess.run([sys.executable, "-m", "moonlighting.run"], cwd=floor,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 2
    assert "must be an integer" in r.stderr


def test_morning_digest_lists_review_and_blocked(tmp_path):
    (tmp_path / "work-orders").mkdir()
    (tmp_path / "night-shift").mkdir()
    (tmp_path / "night-shift" / "NIGHT-SHIFT.md").write_text("# manual\n")
    (tmp_path / "night-shift" / "QA-SHIFT.md").write_text("# qa\n")
    review = ORDER.replace("status: draft", "status: review")
    review += ("\n### 04:00 — night run (engine pi), exit 0 (9s)\n\nreport\n\n"
               "---\n\n### QA pre-shift (engine pi, exit 0)\n\n"
               "**Verdict** — SHIP\n")
    (tmp_path / "work-orders" / "a1b2c3d-a.md").write_text(review)
    blocked = (ORDER.replace("status: draft", "status: blocked")
               .replace("id: a1b2c3d", "id: b2c3d4e"))
    (tmp_path / "work-orders" / "b2c3d4e-b.md").write_text(blocked)
    night = nightrun.NightRun(tmp_path, "pi", None, 5, True, 60)
    night._write_morning_digest()
    digest = tmp_path / "night-shift" / "logs" / f"{night.today}-morning.md"
    text = digest.read_text()
    assert "a1b2c3d" in text and "SHIP" in text
    assert "b2c3d4e" in text and "blocked" in text


def test_rotate_logs_roundtrip(tmp_path):
    root = make_git_repo(tmp_path / "f")
    logs = root / "night-shift" / "logs"
    logs.mkdir(parents=True)
    old = logs / "2026-01-01-wo-001.out.md"
    old.write_text("precious report\n")
    past = time.time() - 86400 * 2
    os.utime(old, (past, past))
    r = subprocess.run([sys.executable, "-m", "moonlighting.rotate_logs",
                        "--days", "1", "--write"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert not old.exists()
    gz = logs / "archive" / "2026-01-01-wo-001.out.md.gz"
    assert gz.exists()
    with gzip.open(gz, "rt") as f:
        assert f.read() == "precious report\n"
    log_line = subprocess.run(
        ["git", "-C", str(root), "log", "--oneline", "-1"],
        capture_output=True, text=True).stdout
    assert "rotate-logs" in log_line


def test_new_order_creates_filled_ids(tmp_path):
    root = make_git_repo(tmp_path / "f")
    (root / "work-orders").mkdir()
    docs = root / "docs"
    docs.mkdir()
    template = Path(__file__).resolve().parents[1] / "docs" / "work-order-template.md"
    (docs / "work-order-template.md").write_text(template.read_text())
    r = subprocess.run([sys.executable, "-m", "moonlighting.new_order",
                        "Atom: feed!"],
                       cwd=root, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    first = list((root / "work-orders").glob("*-atom-feed.md"))
    assert len(first) == 1
    sha = first[0].name.split("-")[0]
    assert re.fullmatch(r"[0-9a-f]{7}", sha)
    text = first[0].read_text()
    assert f"id: {sha}" in text and "title: Atom: feed!" in text
    assert f"created: {date.today().isoformat()}" in text
    assert f"branch: wo/{sha}" in text
    r2 = subprocess.run([sys.executable, "-m", "moonlighting.new_order",
                         "Second thing"],
                        cwd=root, capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    second = list((root / "work-orders").glob("*-second-thing.md"))
    assert len(second) == 1
    assert second[0].name.split("-")[0] != sha


def test_new_order_repo_and_model_fields(tmp_path):
    root = make_git_repo(tmp_path / "f")
    target = make_git_repo(tmp_path / "shop")
    (root / "work-orders").mkdir()
    docs = root / "docs"
    docs.mkdir()
    template = Path(__file__).resolve().parents[1] / "docs" / "work-order-template.md"
    (docs / "work-order-template.md").write_text(template.read_text())
    r = subprocess.run(
        [sys.executable, "-m", "moonlighting.new_order", "Chore",
         "--repo", str(target), "--model", "x/y:high"],
        cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    created = list((root / "work-orders").glob("*-chore.md"))
    assert len(created) == 1
    text = created[0].read_text()
    assert f"repo: {target}" in text
    assert "model: x/y:high" in text
    assert "lint: clean" in r.stdout


def test_answer_and_feedback_roundtrip(tmp_path):
    root = make_git_repo(tmp_path / "f")
    (root / "work-orders").mkdir()
    blocked = GOOD_APPROVED.replace("status: approved", "status: blocked")
    (root / "work-orders" / "a1b2c3d-b.md").write_text(blocked)
    review = GOOD_APPROVED.replace("status: approved", "status: review")
    (root / "work-orders" / "b2c3d4e-r.md").write_text(review)

    r1 = subprocess.run(
        [sys.executable, "-m", "moonlighting.answer", "a1b2c3d",
         "use the other path"],
        cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r1.returncode == 0, r1.stderr
    t1 = (root / "work-orders" / "a1b2c3d-b.md").read_text()
    assert "status: approved" in t1 and "use the other path" in t1
    assert "day shift decision" in t1

    r2 = subprocess.run(
        [sys.executable, "-m", "moonlighting.feedback", "b2c3d4e", "add tests"],
        cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r2.returncode == 0, r2.stderr
    t2 = (root / "work-orders" / "b2c3d4e-r.md").read_text()
    assert "status: blocked" in t2 and "add tests" in t2

    r3 = subprocess.run(
        [sys.executable, "-m", "moonlighting.feedback", "a1b2c3d", "nope"],
        cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r3.returncode == 1
    assert "not 'review'" in r3.stderr


def test_approve_script(tmp_path):
    root = make_git_repo(tmp_path / "f")
    (root / "work-orders").mkdir()
    (root / "work-orders" / "a1b2c3d-d.md").write_text(ORDER)
    r = subprocess.run([sys.executable, "-m", "moonlighting.approve", "a1b2c3d"],
                       cwd=root, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    text = (root / "work-orders" / "a1b2c3d-d.md").read_text()
    assert "status: approved" in text


def test_remove_deletes_order(tmp_path):
    root = make_git_repo(tmp_path / "f")
    wo = root / "work-orders"
    wo.mkdir()
    target = wo / "a1b2c3d-old.md"
    target.write_text(ORDER)

    r = subprocess.run(
        [sys.executable, "-m", "moonlighting.remove", "a1b2c3d"],
        cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 1
    assert "refusing to delete" in r.stderr
    assert target.exists()

    r2 = subprocess.run(
        [sys.executable, "-m", "moonlighting.remove", "a1b2c3d", "--yes"],
        cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r2.returncode == 0, r2.stderr
    assert not target.exists()

    r3 = subprocess.run(
        [sys.executable, "-m", "moonlighting.remove", "zzzzzzz", "--yes"],
        cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r3.returncode == 1
    assert "found 0" in r3.stderr
