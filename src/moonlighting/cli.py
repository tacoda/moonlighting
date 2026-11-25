"""The moonlighting command: one binary for every workflow.

    moonlighting night --engine pi
    moonlighting new-order "Title"
"""

from __future__ import annotations

import sys

from moonlighting import (
    accept,
    answer,
    approve,
    factory,
    feedback,
    lint_orders,
    new_order,
    rotate_logs,
    run,
    schedule,
    status,
)

COMMANDS = {
    "accept": accept.main,
    "answer": answer.main,
    "approve": approve.main,
    "feedback": feedback.main,
    "lint-orders": lint_orders.main,
    "new-order": new_order.main,
    "night": run.main,
    "rotate-logs": rotate_logs.main,
    "schedule": schedule.main,
    "status": status.main,
}


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] not in COMMANDS:
        known = ", ".join(sorted(COMMANDS))
        print(f"usage: moonlighting <command> [...]\ncommands: {known}",
              file=sys.stderr)
        raise SystemExit(2)
    command = sys.argv.pop(1)
    try:
        COMMANDS[command]()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)


if __name__ == "__main__":
    main()
