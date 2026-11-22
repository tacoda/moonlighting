#!/usr/bin/env python3
"""night-shift/run.py — execute approved work orders headlessly.

Each order names its target repo via the `repo:` frontmatter field (default:
this factory; a path or git URL points elsewhere — URLs are cloned under
repos/). The agent works on the order's branch inside a throwaway git
worktree, so the target's own working copy is never switched or touched;
the runner does all bookkeeping (status flips, logs) in the factory repo.

Run one factory process per target repo — locks make double-running visible.
See docs/runbook.md.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Execute approved work orders (night shift).")
    ap.add_argument("--engine", default=os.environ.get("FACTORY_ENGINE", "pi"),
                    help="host agent: pi (default) or claude; env FACTORY_ENGINE")
    ap.add_argument("--repo", default=None, metavar="REPO",
                    help="only process orders for this repo (path or git URL)")
    ap.add_argument("--max-orders", type=int, default=1,
                    help="run at most N orders (default: 1)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would run, change nothing")
    args = ap.parse_args()

    binary = factory.engine_bin(args.engine)
    timeout_secs = int(os.environ.get("NIGHT_TIMEOUT_SECS", "7200"))

    root = factory.repo_root()
    os.chdir(root)

    if not (root / "work-orders").is_dir():
        factory.die("no work-orders/ directory — this is not a factory floor")

    branch = factory.git_out(root, "branch", "--show-current")
    if branch != "main":
        factory.die(f"start the night shift from main (you are on: {branch})")
    if not factory.clean_tree(root):
        factory.die("working tree must be clean before the night shift (commit or stash)")

    locks = root / "night-shift" / "locks"
    factory_lock = factory.acquire_lock(locks, "factory", f"factory checkout {root}")
    try:
        run_night(root, args, binary, timeout_secs, locks)
    finally:
        factory.release_lock(factory_lock)


def run_night(root: Path, args, binary: str, timeout_secs: int, locks: Path) -> None:
    def show(target: Path | None) -> str:
        if target is None:
            return "?"
        return factory.display_target(root, target)

    filter_target = None
    if args.repo:
        filter_target = factory.resolve_target(root, args.repo)

    queue = []
    for order in sorted((root / "work-orders").glob("*.md")):
        fields = factory.parse_order(order)
        if fields.get("status") != "approved":
            continue
        problems = factory.lint_order(order, root)
        if problems:
            # malformed orders are blocked without spending tokens; the run
            # keeps its honesty by stopping rather than skipping silently
            queue.append((order, fields, None, problems))
            continue
        target = factory.resolve_target(root, fields.get("repo"))
        if filter_target is not None and target != filter_target:
            continue
        queue.append((order, fields, target, []))

    if not queue:
        print("nothing approved" + (" for this repo" if filter_target else "")
              + " — nothing to do tonight.")
        return

    print(f"night shift queue (engine: {args.engine}):")
    for order, fields, target, problems in queue:
        lint = "" if not problems else f"  [lint: {len(problems)} problem(s)]"
        print(f"  {order.relative_to(root)}  ->  {show(target)}{lint}")
    if args.dry_run:
        return

    logs = root / "night-shift" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    today = f"{datetime.now():%Y-%m-%d}"
    run_log = logs / f"{today}.md"
    sessions_file = root / "night-shift" / "sessions.json"
    system_prompt = (root / "night-shift" / "NIGHT-SHIFT.md").read_text()
    qa_system_prompt = (root / "night-shift" / "QA-SHIFT.md").read_text()
    json_audit = os.environ.get("FACTORY_JSON_AUDIT", "1") != "0"
    qa_enabled = os.environ.get("FACTORY_QA", "1") != "0"

    ran = 0
    failed: str | None = None
    for order, fields, target, problems in queue:
        if ran >= args.max_orders:
            break
        rel = order.relative_to(root)
        order_id = fields.get("id", "")
        if not order_id:
            print(f"skip {rel}: no id in frontmatter")
            continue
        order_branch = fields.get("branch") or f"wo/{order_id}"

        # ---- lint gate: malformed orders are blocked before anything runs
        if problems:
            print(f"\n=== wo-{order_id} : {rel}  ->  BLOCKED by lint ===")
            for p in problems:
                print(f"  - {p}")
            report = ("**Status** — BLOCKED (by lint, before the agent started)\n\n"
                      + "\n".join(f"- {p}" for p in problems))
            with order.open("a") as f:
                f.write(f"\n### {datetime.now():%Y-%m-%d %H:%M} — blocked by lint\n\n")
                f.write(report)
            factory.set_status(order, "blocked")
            factory.git(root, "add", str(rel), "night-shift/logs")
            factory.git(root, "commit", "-q", "-m",
                        f"night-shift: wo-{order_id} -> blocked (lint)")
            print(f"wo-{order_id} -> blocked (lint)")
            failed = order_id
            break

        print(f"\n=== wo-{order_id} : {rel}  ->  {show(target)} ===")

        # ---- the night runs in a throwaway worktree of the target repo,
        # under a lock; the target's own working copy is never switched
        repo_lock = factory.acquire_lock(locks, factory.repo_slug(target),
                                         f"repo {show(target)}")
        rc, report, run_err, secs = 0, "", "", 0
        worktrees = root / "night-shift" / "worktrees"
        wpath = worktrees / factory.repo_slug(target) / f"wo-{order_id}"
        try:
            started = time.monotonic()

            if not factory.clean_tree(target):
                print(f"note: {show(target)} has uncommitted changes — "
                      f"isolated from the night (it runs in a worktree)")
            factory.git(target, "worktree", "prune")
            if wpath.exists():
                factory.die(f"worktree path already exists: {wpath} — remove it "
                            f"before rerunning this order")
            bref = factory.base_ref(root, target)
            branch_exists = factory.git(target, "show-ref", "--verify", "--quiet",
                                        f"refs/heads/{order_branch}",
                                        check=False).returncode == 0
            if branch_exists:
                factory.git(target, "worktree", "add", str(wpath), order_branch)
                print(f"resuming branch {order_branch} in a worktree")
            else:
                factory.git(target, "worktree", "add", "-b", order_branch,
                            str(wpath), bref)
                print(f"new branch {order_branch} (from {bref}) in a worktree")

            try:
                prompt = (f"Execute work order {order_id} now, following the "
                          f"night-shift manual in your system prompt.\n\n"
                          f"# Work order {order_id}\n\n{order.read_text()}")

                sessions = factory.load_sessions(sessions_file)
                argv, new_ref = factory.build_command(
                    args.engine, binary, system_prompt, prompt,
                    f"wo-{order_id}", sessions.get(f"{args.engine}:{order_id}"),
                    json_audit=json_audit)
                if new_ref:
                    sessions[f"{args.engine}:{order_id}"] = new_ref
                    factory.save_sessions(sessions_file, sessions)

                # agent output is captured outside any working tree: anything
                # written there could be swept onto a branch and vanish with
                # a later checkout
                raw_events = ""
                with tempfile.TemporaryDirectory() as tmp:
                    out_path = Path(tmp) / "out.md"
                    err_path = Path(tmp) / "err.log"
                    try:
                        with out_path.open("w") as out, err_path.open("w") as err:
                            proc = subprocess.run(argv, cwd=wpath, stdout=out,
                                                  stderr=err, timeout=timeout_secs)
                            rc = proc.returncode
                    except subprocess.TimeoutExpired:
                        rc = 124
                    except FileNotFoundError:
                        factory.die(f"engine executable not found: {binary} "
                                    f"(set PI_BIN or CLAUDE_BIN)", 127)
                    raw_events = out_path.read_text()
                    run_err = err_path.read_text()
                report = (factory.extract_report(args.engine, raw_events)
                          if json_audit else raw_events)

                secs = int(time.monotonic() - started)

                # the agent must leave a committed branch; sweep up what it forgot
                if not factory.clean_tree(wpath):
                    factory.git(wpath, "add", "-A")
                    factory.git(wpath, "commit", "-q", "-m",
                                f"wo-{order_id}: night-shift WIP (auto-committed by runner)")
                    print(f"note: uncommitted work was auto-committed to {order_branch}")

                # ---- QA pre-shift: verify, don't trust (advisory only)
                qa_rc = None
                qa_raw = ""
                qa_report = ""
                if rc == 0 and qa_enabled:
                    qa_prompt = (
                        f"QA pre-shift for work order {order_id}: the night shift "
                        f"implemented it on branch {order_branch}, checked out here. "
                        f"Review it against {bref}. Follow the QA manual.\n\n"
                        f"# Work order {order_id}\n\n{order.read_text()}")
                    sessions = factory.load_sessions(sessions_file)
                    qargv, qref = factory.build_command(
                        args.engine, binary, qa_system_prompt, qa_prompt,
                        f"qa-{order_id}", sessions.get(f"{args.engine}:qa:{order_id}"),
                        json_audit=json_audit)
                    if qref:
                        sessions[f"{args.engine}:qa:{order_id}"] = qref
                        factory.save_sessions(sessions_file, sessions)
                    print(f"QA pre-shift reviewing wo-{order_id} ...")
                    qa_rc = 0
                    with tempfile.TemporaryDirectory() as qtmp:
                        qout = Path(qtmp) / "out.md"
                        qerr = Path(qtmp) / "err.log"
                        try:
                            with qout.open("w") as out, qerr.open("w") as err:
                                qproc = subprocess.run(qargv, cwd=wpath, stdout=out,
                                                       stderr=err, timeout=timeout_secs)
                                qa_rc = qproc.returncode
                        except subprocess.TimeoutExpired:
                            qa_rc = 124
                        qa_raw = qout.read_text()
                    qa_report = (factory.extract_report(args.engine, qa_raw)
                                 if json_audit else qa_raw)
                    print(f"QA pre-shift done (exit {qa_rc})")
            finally:
                # the worktree is disposable; the branch keeps everything.
                # --force: ignored artifacts (node_modules etc.) are not source
                r = factory.git(target, "worktree", "remove", str(wpath), check=False)
                if r.returncode != 0:
                    factory.git(target, "worktree", "remove", "--force", str(wpath))
        finally:
            factory.release_lock(repo_lock)

        # ---- bookkeeping: factory repo only; the branch holds the night's work
        new_status = "review" if rc == 0 else "blocked"
        outfile = logs / f"{today}-wo-{order_id}.out.md"
        errfile = logs / f"{today}-wo-{order_id}.err.log"
        outfile.write_text(report)
        errfile.write_text("" if rc == 0 else run_err)
        if json_audit:
            (logs / f"{today}-wo-{order_id}.events.jsonl").write_text(raw_events)
        if qa_raw:
            (logs / f"{today}-wo-{order_id}.qa.jsonl").write_text(qa_raw)

        with order.open("a") as f:
            f.write(f"\n### {datetime.now():%Y-%m-%d %H:%M} — night run "
                    f"(engine {args.engine}, target {show(target)}), exit {rc} ({secs}s)\n\n")
            f.write(report)
            if rc != 0:
                f.write(f"\n> run FAILED (exit {rc}). stderr: {errfile.relative_to(root)}\n")
            if qa_rc is not None:
                f.write(f"\n---\n\n### QA pre-shift (engine {args.engine}, exit {qa_rc})\n\n")
                f.write(qa_report or "(empty QA report)")

        factory.set_status(order, new_status)

        with run_log.open("a") as f:
            qa_note = f", qa exit {qa_rc}" if qa_rc is not None else ""
            f.write(f"\n## {datetime.now():%H:%M} run\n")
            f.write(f"- wo-{order_id} ({rel}) -> {show(target)}: {new_status}, "
                    f"engine {args.engine}, exit {rc}{qa_note}, {secs}s — "
                    f"report in order file; raw: {outfile.relative_to(root)}\n")

        add_paths = [str(rel), "night-shift/logs"]
        if args.engine == "claude":
            add_paths.append("night-shift/sessions.json")
        factory.git(root, "add", *add_paths)
        factory.git(root, "commit", "-q", "-m",
                    f"night-shift: wo-{order_id} -> {new_status} (exit {rc}, {secs}s)")

        print(f"wo-{order_id} -> {new_status} ({secs // 60}m{secs % 60:02d}s)")

        ran += 1
        if new_status == "blocked":
            failed = order_id
            break

    print(f"\nnight shift over: {ran} order(s) processed.")
    if failed:
        print(f"wo-{failed} is blocked — run stopped. See {run_log.relative_to(root)}")
    print("morning: python3 day-shift/status.py")


if __name__ == "__main__":
    main()
