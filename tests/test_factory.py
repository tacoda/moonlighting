"""Tests for the factory object model, engine adapters and locks.

Run with: uv run pytest
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import factory

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
    argv, ref = factory.engine("pi").build_command(SYSTEM, PROMPT, "wo-001", None)
    assert argv[0] == "pi"
    assert "--print" in argv
    assert "--approve" in argv
    assert "--mode" in argv and "json" in argv
    assert "--session-id" in argv and "wo-001" in argv
    assert argv[-1] == PROMPT
    assert ref is None


def test_pi_command_no_audit():
    argv, _ = factory.engine("pi").build_command(SYSTEM, PROMPT, "wo-001", None,
                                                 json_audit=False)
    assert "--mode" not in argv


def test_claude_command_new_session():
    argv, ref = factory.engine("claude").build_command(SYSTEM, PROMPT, "x", None)
    assert "--resume" not in argv
    index = argv.index("--session-id")
    assert argv[index + 1] == ref


def test_claude_command_resume():
    argv, ref = factory.engine("claude").build_command(SYSTEM, PROMPT, "x",
                                                       "uuid-1")
    assert "--resume" in argv and "uuid-1" in argv
    assert ref == "uuid-1"


def test_opencode_command_new_session():
    argv, ref = factory.engine("opencode").build_command(SYSTEM, PROMPT, "x", None)
    assert argv[:4] == ["opencode", "run", "--auto", "--archived"]
    assert "--session" not in argv
    assert argv[-1] == f"{SYSTEM}\n\n---\n\n{PROMPT}"
    assert ref is None


def test_opencode_command_resume():
    argv, _ = factory.engine("opencode").build_command(SYSTEM, PROMPT, "x",
                                                       "ses_abc")
    assert argv[argv.index("--session") + 1] == "ses_abc"


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


def test_lock_empty_file_is_fatal_today(tmp_path):
    # Current behavior: the runner can never break an empty lock. Flip
    # this test when it learns to treat empty locks as stale.
    (tmp_path / "k.lock").write_text("")
    with pytest.raises(factory.FactoryError), factory.Lock(tmp_path, "k", "repo x"):
            pass


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
