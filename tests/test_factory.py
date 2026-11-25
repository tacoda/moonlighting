"""Tests for the factory object model, engine adapters and locks.

Run with: uv run pytest. Git-touching paths run against fakes. No test
needs a real repository or network; the only real subprocesses are
plain python children.
"""

import contextlib
import gzip
import json
import os
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest

from moonlighting import accept, factory, schedule
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

GOOD_APPROVED = ORDER.replace("status: draft", "status: approved")
BROKEN_APPROVED = (ORDER.replace("status: draft", "status: approved")
                   .replace("id: a1b2c3d", "id: b2c3d4e")
                   .replace("- Step one.\n", ""))


class _R:
    """Minimal subprocess.CompletedProcess stand-in."""

    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


class FakeRepo(factory.TargetRepo):
    """TargetRepo subclass: every git answer is canned."""

    def __init__(self, path):
        self.path = Path(path)
        self.profile_name = ""
        self.engine: str | None = None
        self.model: str | None = None
        self.qa_model: str | None = None
        self.plan_model: str | None = None

    def display(self):
        return str(self.path)

    def slug(self):
        return self.path.name

    def env(self):
        return super().env()

    def is_dirty(self):
        return False

    def current_branch(self):
        return "main"

    def local_main(self):
        return "main"

    def base_ref(self):
        return "origin/main"

    def branch_exists(self, name):
        return True


def patch_resolve(monkeypatch, mapping):
    """TargetRepo.resolve answers from a {value: repo-or-None} dict."""
    monkeypatch.setattr(
        factory.TargetRepo, "resolve",
        classmethod(lambda cls, value, update=True, soft=False:
                    mapping.get(value)))


def make_order(tmp_path, text=ORDER, name="a1b2c3d-test.md"):
    path = tmp_path / name
    path.write_text(text)
    return factory.WorkOrder(path)


def fake_floor():
    """Floor with the orders and logs directories ready."""
    fl = factory.floor()
    fl["orders"].mkdir(parents=True, exist_ok=True)
    fl["logs"].mkdir(parents=True, exist_ok=True)
    return fl


def run_module(module, *args):
    """Run a workflow module as a child with the isolated env inherited."""
    return subprocess.run([sys.executable, "-m", f"moonlighting.{module}",
                           *args], check=False, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


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


def test_lint_rejects_self_repo(tmp_path):
    text = ORDER.replace("---\n", "---\nrepo: self\n", 1)
    problems = make_order(tmp_path, text).lint()
    assert any("named no target" in p for p in problems)


def test_lint_id_filename_mismatch(tmp_path):
    order = make_order(tmp_path, name="007-mismatch.md")
    problems = order.lint()
    assert any("does not match the filename prefix" in p for p in problems)


def test_lint_rejects_bad_id_format(tmp_path):
    text = ORDER.replace("id: a1b2c3d", "id: zebra-12")
    problems = make_order(tmp_path, text).lint()
    assert any("7-char hex sha" in p for p in problems)


def test_workorder_model_field(tmp_path):
    text = ORDER.replace("---\n", "---\nmodel: anthropic/claude-opus-5\n", 1)
    order = make_order(tmp_path, text)
    assert order.model == "anthropic/claude-opus-5"
    assert make_order(tmp_path).model == ""


def test_lint_rejects_model_with_whitespace(tmp_path):
    text = ORDER.replace("---\n", "---\nmodel: claude opus\n", 1)
    problems = make_order(tmp_path, text).lint()
    assert any("model" in p for p in problems)


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


def test_codex_command():
    argv, ref, stdin_text = factory.engine("codex").build_command(
        SYSTEM, PROMPT, "x", None, model="gpt-5.1-codex")
    assert argv[0] == "codex"
    assert "--json" in argv
    assert "--dangerously-bypass-approvals-and-sandbox" in argv
    assert "--skip-git-repo-check" in argv
    assert "--model" in argv and "gpt-5.1-codex" in argv
    assert ref is None
    assert stdin_text == f"{SYSTEM}\n\n---\n\n{PROMPT}"


def test_codex_extract_jsonl():
    eng = factory.engine("codex")
    raw = "\n".join([
        '{"type":"session_configured"}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}',
        "not json",
    ])
    assert eng.extract_report(raw) == "done"
    assert eng.extract_report("plain") == "plain"
    assert eng.ref_from_output(raw) is None


def test_config_extends_harness(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[harness.crew]\nbinary = "crew-chat"\n'
                   'run = ["run", "--headless"]\nsystem = "stdin"\n'
                   'stdin = "system+prompt"\nsession = "none"\n'
                   'audit = []\nextract = "raw"\n')
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg))
    eng = factory.engine("crew")
    argv, ref, stdin_text = eng.build_command(SYSTEM, PROMPT, "x", None)
    assert argv[:3] == ["crew-chat", "run", "--headless"]
    assert stdin_text == f"{SYSTEM}\n\n---\n\n{PROMPT}"


def test_status_json_branch_name():
    orders = factory.orders_dir()
    orders.mkdir(parents=True)
    (orders / "aaa1111-d.md").write_text(
        ORDER.replace("status: draft", "status: review")
             .replace("id: a1b2c3d", "id: aaa1111"))
    r = run_module("status", "--json")
    items = json.loads(r.stdout)
    assert items[0]["branch"] == "wo/aaa1111"
    assert items[0]["status"] == "review"


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


def test_resolve_self_is_rejected():
    with pytest.raises(factory.FactoryError):
        factory.TargetRepo.resolve("self")


def test_resolve_empty_is_rejected_soft():
    assert factory.TargetRepo.resolve("", soft=True) is None


def test_resolve_missing_path_soft(tmp_path):
    missing = str(tmp_path / "nope")
    assert factory.TargetRepo.resolve(missing, update=False, soft=True) is None


def test_resolve_url_not_cloned_soft():
    assert factory.TargetRepo.resolve("https://example.com/x.git",
                                      update=False, soft=True) is None


def test_repo_name_resolution_and_identity(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text('[profile.work]\nname = "Work Bot"\n'
                   'email = "bot@work.example"\n\n'
                   f'[repo.demo]\npath = "{target}"\nprofile = "work"\n')
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg))
    monkeypatch.setattr(factory.subprocess, "run", lambda *a, **k: _R(0))
    repo = factory.TargetRepo.resolve("demo")
    assert repo is not None
    assert repo.path == target.resolve()
    assert repo.profile_name == "work"
    env = repo.env()
    assert env["GIT_AUTHOR_NAME"] == "Work Bot"
    assert env["GIT_AUTHOR_EMAIL"] == "bot@work.example"


def test_resolve_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / "config.toml"
    cfg.write_text('[repo.tilde]\npath = "~/realrepo"\n')
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg))
    monkeypatch.setattr(factory.subprocess, "run", lambda *a, **k: _R(0))
    repo = factory.TargetRepo.resolve("tilde", update=False)
    assert repo is not None
    assert repo.path == (tmp_path / "realrepo").resolve()


# -------------------------------------------------------------- helpers


def test_is_repo_url():
    assert factory.is_repo_url("https://github.com/a/b.git")
    assert factory.is_repo_url("git@github.com:a/b.git")
    assert not factory.is_repo_url("relative/path")


def test_repo_slug():
    assert factory.repo_slug(Path("/a b/c")) == "_a_b_c"


def test_git_failure_raises_factory_error(tmp_path):
    with pytest.raises(factory.FactoryError):
        factory.git(tmp_path, "log", "-1")


def test_git_check_false_stays_quiet(tmp_path):
    r = factory.git(tmp_path, "log", "-1", check=False)
    assert r.returncode != 0


def test_run_under_timeout_feeds_stdin(tmp_path):
    script = tmp_path / "reader.py"
    script.write_text("import sys\nsys.stdout.write(sys.stdin.read().upper())\n")
    out, err = tmp_path / "out", tmp_path / "err"
    rc = factory.run_under_timeout([sys.executable, str(script)], tmp_path, 30,
                                   out, err, input_text="ping")
    assert rc == 0
    assert out.read_text() == "PING"


def test_run_under_timeout_kills_hang(tmp_path):
    script = tmp_path / "hang.py"
    script.write_text("import time\ntime.sleep(60)\n")
    out, err = tmp_path / "out", tmp_path / "err"
    start = time.monotonic()
    rc = factory.run_under_timeout([sys.executable, str(script)], tmp_path, 2,
                                   out, err)
    assert rc != 0
    assert time.monotonic() - start < 30


# ------------------------------------------------------- locations


def test_orders_dir_overrides(tmp_path, monkeypatch):
    assert factory.orders_dir() == factory.data_dir() / "orders"
    monkeypatch.setenv("FACTORY_ORDERS_DIR", str(tmp_path / "inbox"))
    assert factory.orders_dir() == tmp_path / "inbox"


def test_config_sets_orders_dir(tmp_path, monkeypatch):
    inbox = str(tmp_path / "inbox")
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[factory]\norders-dir = "{inbox}"\n')
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg))
    assert factory.orders_dir() == tmp_path / "inbox"
    monkeypatch.setenv("FACTORY_ORDERS_DIR", str(tmp_path / "envdir"))
    assert factory.orders_dir() == tmp_path / "envdir"


def test_floor_dirs_live_under_data_dir():
    fl = factory.floor()
    data = factory.data_dir()
    assert fl["orders"] == data / "orders"
    assert fl["logs"] == data / "logs"
    assert fl["locks"] == data / "locks"
    assert fl["worktrees"] == data / "worktrees"
    assert fl["sessions"] == data / "sessions.json"
    assert fl["manual"].is_file()  # the manual ships inside the package
    assert factory.packaged_template().is_file()


# ------------------------------------------------------------ the night


def test_collect_splits_healthy_from_problems(tmp_path, monkeypatch):
    fl = fake_floor()
    good = GOOD_APPROVED.replace("---\n", "---\nrepo: shop\n", 1)
    bad = BROKEN_APPROVED.replace("---\n", "---\nrepo: shop\n", 1)
    (fl["orders"] / "a1b2c3d-good.md").write_text(good)
    (fl["orders"] / "b2c3d4e-bad.md").write_text(bad)
    patch_resolve(monkeypatch, {"shop": FakeRepo(tmp_path / "shop")})
    night = nightrun.NightRun(fl, "pi", None, 5, True, 60)
    healthy, problems, skipped = night.collect()
    assert [o.id for o, _ in healthy] == ["a1b2c3d"]
    assert [o.id for o, _ in problems] == ["b2c3d4e"]
    assert skipped == 0


def test_collect_blocks_order_without_repo(tmp_path):
    fl = fake_floor()
    (fl["orders"] / "a1b2c3d-norepo.md").write_text(GOOD_APPROVED)
    night = nightrun.NightRun(fl, "pi", None, 5, True, 60)
    _, problems, _ = night.collect()
    assert any("names no target repo" in p[1][0] for p in problems)


def test_run_empty_filter_lists_other_repos(tmp_path, monkeypatch, capsys):
    fl = fake_floor()
    shop = FakeRepo(tmp_path / "shop")
    other = FakeRepo(tmp_path / "other")
    order = GOOD_APPROVED.replace("---\n", "---\nrepo: shop\n", 1)
    (fl["orders"] / "a1b2c3d-shop.md").write_text(order)
    patch_resolve(monkeypatch, {"shop": shop, "other": other})
    nightrun.NightRun(fl, "pi", "other", 5, True, 60).run()
    out = capsys.readouterr().out
    assert "nothing approved for this repo" in out
    assert "approved orders exist for other repos" in out
    assert "a1b2c3d" in out and "shop" in out


def test_morning_digest_lists_review_and_blocked():
    fl = fake_floor()
    review = ORDER.replace("status: draft", "status: review")
    review += ("\n### 04:00 — night run (engine pi), exit 0 (9s)\n\nreport\n\n"
               "---\n\n### QA pre-shift (engine pi, exit 0)\n\n"
               "**Verdict** — SHIP\n")
    (fl["orders"] / "a1b2c3d-a.md").write_text(review)
    blocked = (ORDER.replace("status: draft", "status: blocked")
               .replace("id: a1b2c3d", "id: b2c3d4e"))
    (fl["orders"] / "b2c3d4e-b.md").write_text(blocked)
    night = nightrun.NightRun(fl, "pi", None, 5, True, 60)
    night._write_morning_digest()
    digest = fl["logs"] / f"{night.today}-morning.md"
    text = digest.read_text()
    assert "a1b2c3d" in text and "SHIP" in text
    assert "b2c3d4e" in text and "blocked" in text


def test_night_process_flips_to_review(tmp_path, monkeypatch, capsys):
    fl = fake_floor()
    (fl["orders"] / "aaa1111-demo.md").write_text(
        ORDER.replace("id: a1b2c3d", "id: aaa1111")
             .replace("status: draft", "status: approved")
             .replace("---\n", "---\nrepo: shop\n", 1))
    repo = FakeRepo(tmp_path / "shop")
    patch_resolve(monkeypatch, {"shop": repo})

    @contextlib.contextmanager
    def fake_worktree(repo_, path, branch, base):
        path.mkdir(parents=True, exist_ok=True)
        yield type("FakeWt", (), {"path": path})()

    monkeypatch.setattr(factory, "Worktree", fake_worktree)
    monkeypatch.setattr(factory, "git", lambda cwd, *a, check=True, env=None:
                        _R(0))
    monkeypatch.setattr(factory, "git_out", lambda cwd, *a: "2")
    monkeypatch.setattr(nightrun.NightRun, "_agent_pass",
                        lambda self, argv, cwd, engine, stdin_text=None,
                        timeout_secs=None, env_extra=None:
                        (0, '{"events": true}', ""))
    monkeypatch.setattr(nightrun.NightRun, "_qa_pass",
                        lambda self, *a, **k: (0, "", "QA ok", False))
    night = nightrun.NightRun(fl, "pi", None, 1, False, 60)
    night.run()
    text = (fl["orders"] / "aaa1111-demo.md").read_text()
    assert "status: review" in text
    assert (fl["logs"] / f"{night.today}-wo-aaa1111.out.md").exists()
    assert "night shift over: 1 order(s)" in capsys.readouterr().out


def test_preflight_failure_lands_in_errors_log(tmp_path):
    env = dict(os.environ, MOONLIGHTING_DATA=str(tmp_path / "data"),
               MOONLIGHTING_CONFIG=str(tmp_path / "c.toml"))
    r = subprocess.run([sys.executable, "-m", "moonlighting.run"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1
    log = tmp_path / "data" / "logs" / "errors.log"
    assert "work orders directory" in log.read_text()


def test_night_timeout_guard(tmp_path):
    env = dict(os.environ, NIGHT_TIMEOUT_SECS="abc",
               MOONLIGHTING_DATA=str(tmp_path / "data"),
               MOONLIGHTING_CONFIG=str(tmp_path / "c.toml"))
    r = subprocess.run([sys.executable, "-m", "moonlighting.run"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 2
    assert "must be an integer" in r.stderr


# ------------------------------------------------------------- accept


def test_accept_pushes_and_opens_pr(tmp_path, monkeypatch):
    fl = fake_floor()
    (fl["orders"] / "a1b2c3d-x.md").write_text(
        ORDER.replace("status: draft", "status: review")
             .replace("---\n", "---\nrepo: shop\n", 1))
    repo = FakeRepo(tmp_path / "shop")
    patch_resolve(monkeypatch, {"shop": repo})
    pushed = []
    monkeypatch.setattr(factory.TargetRepo, "branch_exists",
                        lambda self, name: True)
    monkeypatch.setattr(factory, "git_out", lambda cwd, *a:
                        "tacoda_github:tacoda/tacoda.github.io"
                        if "get-url" in a else "3")
    monkeypatch.setattr(factory, "git",
                        lambda cwd, *a, check=True, env=None:
                        pushed.append(a) or _R(0))
    gh_calls = []

    def fake_gh(args, env=None):
        gh_calls.append((args, env))
        return _R(0, "https://github.com/tacoda/tacoda.github.io/pull/7", "")

    cfg = tmp_path / "config.toml"
    cfg.write_text('[profile.work]\ngh-account = "ianparo"\n')
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg))
    stub_token = "stub-gh-token"
    monkeypatch.setattr(factory.subprocess, "run",
                        lambda *a, **k: _R(0, stub_token))
    repo.profile_name = "work"
    monkeypatch.setattr(accept, "gh", fake_gh)
    monkeypatch.setattr(sys, "argv", ["moonlighting", "a1b2c3d"])
    accept.main()
    text = (fl["orders"] / "a1b2c3d-x.md").read_text()
    assert "status: review" in text
    assert "PR opened: https://github.com/tacoda/tacoda.github.io/pull/7" in text
    assert ("push", "origin", "wo/a1b2c3d") in pushed
    args, env = gh_calls[0]
    assert args[0] == "pr" and "--head" in args
    assert "--repo" in args and "tacoda/tacoda.github.io" in args
    assert env.get("GH_TOKEN") == stub_token


def test_accept_refuses_draft(tmp_path, capsys):
    fl = fake_floor()
    (fl["orders"] / "a1b2c3d-d.md").write_text(ORDER)
    monkey_argv = ["moonlighting", "a1b2c3d"]
    monkeypatch_argv(monkey_argv)
    with pytest.raises(factory.FactoryError):
        accept.main()


def monkeypatch_argv(argv):
    import sys as _sys
    _sys.argv = argv


# ------------------------------------------------------- day scripts


def test_new_order_creates_filled_ids():
    r = run_module("new_order", "Atom: feed!")
    assert r.returncode == 0, r.stderr
    orders = factory.orders_dir()
    first = list(orders.glob("*-atom-feed.md"))
    assert len(first) == 1
    sha = first[0].name.split("-")[0]
    assert re.fullmatch(r"[0-9a-f]{7}", sha)
    text = first[0].read_text()
    assert f"id: {sha}" in text and "title: Atom: feed!" in text
    assert f"created: {date.today().isoformat()}" in text
    assert f"branch: wo/{sha}" in text
    r2 = run_module("new_order", "Second thing")
    assert r2.returncode == 0, r2.stderr
    second = list(orders.glob("*-second-thing.md"))
    assert len(second) == 1
    assert second[0].name.split("-")[0] != sha


def test_new_order_approve_flag():
    r = run_module("new_order", "Quick", "--approve")
    assert r.returncode == 0, r.stderr
    created = list(factory.orders_dir().glob("*-quick.md"))
    assert len(created) == 1
    assert "status: approved" in created[0].read_text()
    assert "the night picks it up" in r.stdout


def test_new_order_requires_title_when_not_interactive():
    r = run_module("new_order")
    assert r.returncode == 2
    assert "not running interactively" in r.stderr


def test_new_order_repo_and_model_fields():
    r = run_module("new_order", "Chore",
                   "--repo", "https://example.com/acme/shop.git",
                   "--model", "x/y:high")
    assert r.returncode == 0, r.stderr
    created = list(factory.orders_dir().glob("*-chore.md"))
    assert len(created) == 1
    text = created[0].read_text()
    assert "repo: https://example.com/acme/shop.git" in text
    assert "model: x/y:high" in text
    assert "lint: clean" in r.stdout


def test_answer_and_feedback_roundtrip():
    orders = factory.orders_dir()
    orders.mkdir(parents=True)
    blocked = GOOD_APPROVED.replace("status: approved", "status: blocked")
    (orders / "a1b2c3d-b.md").write_text(blocked)
    review = GOOD_APPROVED.replace("status: approved", "status: review")
    (orders / "b2c3d4e-r.md").write_text(review)

    r1 = run_module("answer", "a1b2c3d", "use the other path")
    assert r1.returncode == 0, r1.stderr
    t1 = (orders / "a1b2c3d-b.md").read_text()
    assert "status: approved" in t1 and "use the other path" in t1
    assert "day shift decision" in t1

    r2 = run_module("feedback", "b2c3d4e", "add tests")
    assert r2.returncode == 0, r2.stderr
    t2 = (orders / "b2c3d4e-r.md").read_text()
    assert "status: blocked" in t2 and "add tests" in t2

    r3 = run_module("feedback", "a1b2c3d", "nope")
    assert r3.returncode == 1
    assert "reply needs a review or blocked" in r3.stderr


def test_approve_script():
    orders = factory.orders_dir()
    orders.mkdir(parents=True)
    (orders / "a1b2c3d-d.md").write_text(ORDER)
    r = run_module("approve", "a1b2c3d")
    assert r.returncode == 0, r.stderr
    text = (orders / "a1b2c3d-d.md").read_text()
    assert "status: approved" in text


def test_remove_deletes_order():
    orders = factory.orders_dir()
    orders.mkdir(parents=True)
    target = orders / "a1b2c3d-old.md"
    target.write_text(ORDER)

    r = run_module("remove", "a1b2c3d")
    assert r.returncode == 1
    assert "refusing to delete" in r.stderr
    assert target.exists()

    r2 = run_module("remove", "a1b2c3d", "--yes")
    assert r2.returncode == 0, r2.stderr
    assert not target.exists()

    r3 = run_module("remove", "zzzzzzz", "--yes")
    assert r3.returncode == 1
    assert "found 0" in r3.stderr


def test_rotate_logs_roundtrip():
    logs = factory.data_dir() / "logs"
    logs.mkdir(parents=True)
    old = logs / "2026-01-01-wo-001.out.md"
    old.write_text("precious report\n")
    past = time.time() - 86400 * 2
    os.utime(old, (past, past))
    r = run_module("rotate_logs", "--days", "1", "--write")
    assert r.returncode == 0, r.stderr
    assert not old.exists()
    gz = logs / "archive" / "2026-01-01-wo-001.out.md.gz"
    assert gz.exists()
    with gzip.open(gz, "rt") as f:
        assert f.read() == "precious report\n"


# ------------------------------------------------------------ schedule


def test_install_cron_global_entry(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[factory]\nengine = "pi"\nschedule-at = "17 1"\nschedule-max-orders = 2\n')
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg))
    monkeypatch.setattr(schedule, "current_crontab", lambda: "")
    captured = {}
    monkeypatch.setattr(schedule, "set_crontab",
                        lambda content: captured.update(content=content))
    monkeypatch.setattr(schedule.shutil, "which", lambda name: "/usr/bin/x")
    schedule.install_cron()
    entry = captured["content"].strip().splitlines()[0]
    assert entry.startswith("17 1 * * * ")
    assert "'/usr/bin/x' night --engine pi" in entry
    assert "--max-orders 2" in entry
    assert str(factory.data_dir() / "logs" / "cron.log") in entry
    assert schedule.TAG in entry


def test_install_cron_replaces_old_entry(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[factory]\nengine = "pi"\n')
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg))
    old = ("0 1 * * * '/usr/bin/moonlighting' night --engine pi "
           ">> /old/cron.log 2>&1 " + schedule.TAG)
    monkeypatch.setattr(schedule, "current_crontab",
                        lambda: f"# other tool\n{old}\n")
    captured = {}
    monkeypatch.setattr(schedule, "set_crontab",
                        lambda content: captured.update(content=content))
    monkeypatch.setattr(schedule.shutil, "which",
                        lambda name: f"/usr/bin/{name}"
                        if name in ("pi", "moonlighting") else None)
    schedule.install_cron()
    content = captured["content"]
    assert content.count(schedule.TAG) == 1
    assert "# other tool" in content
    assert "1 0 * * *" in content  # the default fire time replaced --at


def test_init_cron_flag_installs(monkeypatch, capsys):
    from moonlighting import setup

    monkeypatch.setattr(schedule, "current_crontab", lambda: "")
    monkeypatch.setattr(schedule, "set_crontab", lambda content: None)
    monkeypatch.setattr(schedule.shutil, "which", lambda name: "/usr/bin/x")
    monkeypatch.setattr(sys, "argv", ["moonlighting", "--cron"])
    setup.main()
    assert "night schedule installed" in capsys.readouterr().out


def test_init_no_cron_flag_skips(monkeypatch, capsys):
    from moonlighting import setup

    monkeypatch.setattr(sys, "argv", ["moonlighting", "--no-cron"])
    setup.main()
    assert "cron skipped" in capsys.readouterr().out


def test_repo_binding_harness_fields(tmp_path, monkeypatch):
    target = tmp_path / "t"
    target.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[repo.demo]\npath = "{target}"\nengine = "claude"\n'
                   'model = "alias-9"\nqa-model = "haiku"\n')
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg))
    monkeypatch.setattr(factory.subprocess, "run", lambda *a, **k: _R(0))
    repo = factory.TargetRepo.resolve("demo")
    assert repo is not None
    assert repo.engine == "claude"
    assert repo.model == "alias-9"
    assert repo.qa_model == "haiku"


def test_harness_precedence(tmp_path):
    fl = fake_floor()
    shop = FakeRepo(tmp_path / "shop")
    shop.engine, shop.model, shop.qa_model = "claude", "alias-9", "haiku"
    shop.plan_model = "plank"
    (fl["orders"] / "a1b2c3d-a.md").write_text(
        GOOD_APPROVED.replace("---\n", "---\nrepo: shop\n", 1))
    (fl["orders"] / "b2c3d4e-b.md").write_text(
        ORDER.replace("status: draft", "status: approved")
             .replace("id: a1b2c3d", "id: b2c3d4e")
             .replace("---\n", "---\nrepo: shop\nengine: codex\nmodel: gpt-5\nqa-model: mini\nplan-model: planner-x\n", 1))
    night = nightrun.NightRun(fl, None, None, 5, True, 60)
    order_a = factory.WorkOrder(fl["orders"] / "a1b2c3d-a.md")
    order_b = factory.WorkOrder(fl["orders"] / "b2c3d4e-b.md")
    assert night._harness_for(order_a, shop) == ("claude", "alias-9", "haiku", "plank")
    assert night._harness_for(order_b, shop) == ("codex", "gpt-5", "mini", "planner-x")


def test_flag_engine_beats_repo(tmp_path):
    fl = fake_floor()
    shop = FakeRepo(tmp_path / "shop")
    shop.engine = "claude"
    order = make_order(tmp_path)
    night = nightrun.NightRun(fl, "pi", None, 5, True, 60)
    assert night._harness_for(order, shop)[0] == "pi"


def test_new_order_engine_fields():
    r = run_module("new_order", "Picky", "--draft",
                   "--engine", "codex", "--qa-model", "mini",
                   "--plan-model", "planner")
    assert r.returncode == 0, r.stderr
    created = list(factory.orders_dir().glob("*-picky.md"))
    text = created[0].read_text()
    assert "engine: codex" in text and "qa-model: mini" in text
    assert "plan-model: planner" in text


def test_reject_records_reason_and_status():
    orders = factory.orders_dir()
    orders.mkdir(parents=True)
    (orders / "a1b2c3d-x.md").write_text(GOOD_APPROVED)
    r = run_module("reject", "a1b2c3d", "scope cut")
    assert r.returncode == 0, r.stderr
    text = (orders / "a1b2c3d-x.md").read_text()
    assert "status: rejected" in text
    assert "rejected — scope cut" in text


def test_reject_requires_reason():
    orders = factory.orders_dir()
    orders.mkdir(parents=True)
    (orders / "a1b2c3d-x.md").write_text(GOOD_APPROVED)
    r = run_module("reject", "a1b2c3d")
    assert r.returncode == 2
    assert "usage" in r.stderr


def test_show_prints_the_order():
    orders = factory.orders_dir()
    orders.mkdir(parents=True)
    (orders / "a1b2c3d-x.md").write_text(ORDER)
    r = run_module("show", "a1b2c3d")
    assert r.returncode == 0, r.stderr
    assert "## Goal" in r.stdout


def test_edit_runs_editor_and_lints(tmp_path, monkeypatch):
    stub = tmp_path / "fake_editor.py"
    stub.write_text("#!/usr/bin/env python3\n"
                    "import sys\n"
                    "with open(sys.argv[1], 'a') as f:\n"
                    "    f.write('\\n## Extra\\n- added by editor\\n')\n")
    stub.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(stub))
    orders = factory.orders_dir()
    orders.mkdir(parents=True)
    (orders / "a1b2c3d-x.md").write_text(GOOD_APPROVED)
    r = run_module("edit", "a1b2c3d")
    assert r.returncode == 0, r.stderr
    text = (orders / "a1b2c3d-x.md").read_text()
    assert "added by editor" in text
    assert "lint: clean" in r.stdout


def test_night_plan_pass_feeds_builder(tmp_path, monkeypatch, capsys):
    fl = fake_floor()
    (fl["orders"] / "aaa1111-p.md").write_text(
        ORDER.replace("id: a1b2c3d", "id: aaa1111")
             .replace("status: draft", "status: approved")
             .replace("---\n", "---\nrepo: shop\nplan-model: planner-x\n", 1))
    repo = FakeRepo(tmp_path / "shop")
    patch_resolve(monkeypatch, {"shop": repo})
    calls = []

    @contextlib.contextmanager
    def fake_worktree(repo_, path, branch, base):
        path.mkdir(parents=True, exist_ok=True)
        yield type("FakeWt", (), {"path": path})()

    monkeypatch.setattr(factory, "Worktree", fake_worktree)
    monkeypatch.setattr(factory, "git",
                        lambda cwd, *a, check=True, env=None: _R(0))
    monkeypatch.setattr(factory, "git_out", lambda cwd, *a: "2")

    def fake_agent_pass(self, argv, cwd, engine, stdin_text=None,
                        timeout_secs=None, env_extra=None):
        calls.append(stdin_text)
        if len(calls) == 1:
            return 0, "planner output", ""
        return 0, '{"events": true}', ""

    monkeypatch.setattr(nightrun.NightRun, "_agent_pass", fake_agent_pass)
    monkeypatch.setattr(nightrun.NightRun, "_qa_pass",
                        lambda self, *a, **k: (0, "", "QA ok", False))
    night = nightrun.NightRun(fl, "pi", None, 1, False, 60)
    night.run()
    assert len(calls) == 2
    assert "Plan the implementation" in calls[0]
    assert "Implementation plan" in calls[1]
    assert "planner output" in calls[1]
    text = (fl["orders"] / "aaa1111-p.md").read_text()
    assert "planning pass" in text and "planner output" in text


def test_night_plan_skipped_without_model(tmp_path, monkeypatch):
    fl = fake_floor()
    (fl["orders"] / "aaa1111-p.md").write_text(
        ORDER.replace("id: a1b2c3d", "id: aaa1111")
             .replace("status: draft", "status: approved")
             .replace("---\n", "---\nrepo: shop\n", 1))
    repo = FakeRepo(tmp_path / "shop")
    patch_resolve(monkeypatch, {"shop": repo})
    calls = []

    @contextlib.contextmanager
    def fake_worktree(repo_, path, branch, base):
        path.mkdir(parents=True, exist_ok=True)
        yield type("FakeWt", (), {"path": path})()

    monkeypatch.setattr(factory, "Worktree", fake_worktree)
    monkeypatch.setattr(factory, "git",
                        lambda cwd, *a, check=True, env=None: _R(0))
    monkeypatch.setattr(factory, "git_out", lambda cwd, *a: "2")
    monkeypatch.setattr(nightrun.NightRun, "_agent_pass",
                        lambda self, argv, cwd, engine, stdin_text=None,
                        timeout_secs=None, env_extra=None:
                        calls.append(stdin_text) or (0, "out", ""))
    monkeypatch.setattr(nightrun.NightRun, "_qa_pass",
                        lambda self, *a, **k: (0, "", "QA ok", False))
    night = nightrun.NightRun(fl, "pi", None, 1, False, 60)
    night.run()
    assert len(calls) == 1


def test_qa_pass_extracts_with_the_order_engine(tmp_path, monkeypatch):
    fl = fake_floor()
    night = nightrun.NightRun(fl, "pi", None, 5, True, 60)
    order = make_order(tmp_path)
    wt = tmp_path / "wt"
    wt.mkdir()
    claude_raw = ('{"type":"result","duration_api_ms":1,'
                  '"result":"SHIP\\n\\n**Verdict** — pass"}')
    monkeypatch.setattr(factory, "git_out", lambda cwd, *a: "abc")
    monkeypatch.setattr(
        nightrun.NightRun, "_agent_pass",
        lambda self, argv, cwd, engine, stdin_text=None,
        timeout_secs=None, env_extra=None: (0, claude_raw, ""))
    rc, raw, report, moved = night._qa_pass(
        order, wt, branch="wo/x", base="main",
        engine=factory.engine("claude"), engine_name="claude")
    assert report.startswith("SHIP")
    assert moved is False


def test_reply_parks_review_and_answers_blocked():
    orders = factory.orders_dir()
    orders.mkdir(parents=True)
    (orders / "a1b2c3d-r.md").write_text(
        ORDER.replace("status: draft", "status: review"))
    r = run_module("reply", "a1b2c3d", "add tests")
    assert r.returncode == 0, r.stderr
    text = (orders / "a1b2c3d-r.md").read_text()
    assert "status: blocked" in text
    assert "review \u2192 blocked: add tests" in text
    r2 = run_module("reply", "a1b2c3d", "done, go")
    assert r2.returncode == 0, r2.stderr
    text2 = (orders / "a1b2c3d-r.md").read_text()
    assert "status: approved" in text2
    assert "blocked \u2192 approved: done, go" in text2


def test_harness_engine_required(tmp_path):
    fl = fake_floor()
    shop = FakeRepo(tmp_path / "shop")
    order = make_order(tmp_path)
    night = nightrun.NightRun(fl, None, None, 5, True, 60)
    with pytest.raises(factory.FactoryError) as excinfo:
        night._harness_for(order, shop)
    assert "no engine defined" in str(excinfo.value)


def test_target_repo_harness_fields(tmp_path):
    repo = factory.TargetRepo(tmp_path)
    assert repo.engine is None
    assert repo.model is None
    assert repo.qa_model is None
    assert repo.plan_model is None


def test_github_slug_handles_host_aliases():
    slug = accept.github_slug
    assert slug("git@github.com:acme/shop.git") == "acme/shop"
    assert slug("https://github.com/acme/shop.git") == "acme/shop"
    assert slug("tacoda_github:tacoda/tacoda.github.io") == "tacoda/tacoda.github.io"
    assert slug("/srv/bare/repo") == "bare/repo"


def test_schedule_at_validation(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[factory]\nschedule-at = "99 99"\n')
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg))
    with pytest.raises(factory.FactoryError):
        schedule.install_cron()
