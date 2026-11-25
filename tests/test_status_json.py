"""status --json: the machine-readable floor the Claude Code panel reads."""

import json

from moonlighting import factory, status

ORDER = """---
id: a1b2c3d
title: Test order
status: draft
created: 2026-01-01
---
"""


def test_status_json_lists_orders(monkeypatch, capsys):
    orders = factory.orders_dir()
    orders.mkdir(parents=True, exist_ok=True)
    (orders / "a1b2c3d-test-order.md").write_text(ORDER)
    monkeypatch.setattr("sys.argv", ["status", "--json"])

    status.main()

    rows = json.loads(capsys.readouterr().out)
    assert [(r["id"], r["title"], r["status"]) for r in rows] == [
        ("a1b2c3d", "Test order", "draft")]
