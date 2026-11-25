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


class NightRun:
    """One night shift: collect the approved queue, execute it under locks,
    bookkeep in the factory repo."""

    def __init__(self, root: Path, engine_name: str, repo_filter: str | None,
                 max_orders: int, dry_run: bool, timeout_secs: int):
        self.root = root
        os.chdir(root)
        self.engine_name = engine_name
        self.engine = factory.engine(engine_name)
        self.repo_filter = (factory.TargetRepo.resolve(root, repo_filter)
                            if repo_filter else None)
        self.max_orders = max_orders
        self.dry_run = dry_run
        self.timeout_secs = timeout_secs

        self.logs = root / "night-shift" / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.today = f"{datetime.now():%Y-%m-%d}"
        self.run_log = self.logs / f"{self.today}.md"
        self.worktrees = root / "night-shift" / "worktrees"
        self.sessions = factory.SessionStore(
            root / "night-shift" / "sessions.json")
        self.system_prompt = (root / "night-shift" / "NIGHT-SHIFT.md").read_text()
        self.qa_system_prompt = (root / "night-shift" / "QA-SHIFT.md").read_text()
        self.json_audit = os.environ.get("FACTORY_JSON_AUDIT", "1") != "0"
        self.qa_enabled = os.environ.get("FACTORY_QA", "1") != "0"

    # ------------------------------------------------------------ queue

    def collect(self) -> list[tuple[factory.WorkOrder,
                                    factory.TargetRepo | None,
                                    list[str]]]:
        queue = []
        for path in sorted((self.root / "work-orders").glob("*.md")):
            order = factory.WorkOrder(path, self.root)
            if order.status != "approved":
                continue
            problems = order.lint()
            if problems:
                # malformed orders are blocked without spending tokens; the
                # run keeps its honesty by stopping rather than skipping
                queue.append((order, None, problems))
                continue
            repo = factory.TargetRepo.resolve(self.root, order.repo_value,
                                              soft=True)
            if repo is None:
                # soft resolve. The clone failed or the path is not a git
                # repo. Block this order instead of aborting the night.
                if self.repo_filter is not None:
                    continue
                queue.append((order, None,
                              ["repo: unresolvable (clone failed or not a "
                               "git repository)"]))
                continue
            if self.repo_filter is not None and repo.path != self.repo_filter.path:
                continue
            queue.append((order, repo, []))
        return queue

    # ------------------------------------------------------------ the run

    def run(self) -> None:
        queue = self.collect()
        if not queue:
            print("nothing approved"
                  + (" for this repo" if self.repo_filter else "")
                  + " — nothing to do tonight.")
            return

        print(f"night shift queue (engine: {self.engine_name}):")
        for order, repo, problems in queue:
            lint = "" if not problems else f"  [lint: {len(problems)} problem(s)]"
            target = repo.display() if repo else "(unresolvable)"
            print(f"  {order.rel}  ->  {target}{lint}")
        if self.dry_run:
            return

        ran = 0
        failed: str | None = None
        for order, repo, problems in queue:
            if ran >= self.max_orders:
                break
            if problems or repo is None:
                new_status = self._lint_block(order, problems
                                              or ["repo: unresolvable"])
            else:
                new_status = self._process(order, repo)
            ran += 1
            if new_status == "blocked":
                failed = order.id
                break

        print(f"\nnight shift over: {ran} order(s) processed.")
        if failed:
            print(f"wo-{failed} is blocked — run stopped. See {self.run_log}")
        print("morning: python3 day-shift/status.py")

    # ------------------------------------------------------- per-order flow

    def _process(self, order: factory.WorkOrder,
                 repo: factory.TargetRepo) -> str:
        print(f"\n=== wo-{order.id} : {order.rel}  ->  {repo.display()} ===")

        # the night runs in a throwaway worktree of the target repo, under a
        # lock; the target's own working copy is never switched
        with factory.Lock(self.root / "night-shift" / "locks",
                          repo.slug(), f"repo {repo.display()}"):
            started = time.monotonic()
            rc, report, raw_events, run_err, secs = 0, "", "", "", 0
            qa_rc, qa_raw, qa_report = None, "", ""

            if repo.is_dirty():
                print(f"note: {repo.display()} has uncommitted changes — "
                      f"isolated from the night (it runs in a worktree)")
            base = repo.base_ref()
            with factory.Worktree(repo, self._wpath(repo, order.id),
                                  order.branch, base) as wt:
                prompt = (f"Execute work order {order.id} now, following the "
                          f"night-shift manual in your system prompt.\n\n"
                          f"# Work order {order.id}\n\n{order.path.read_text()}")
                ref = self.sessions.ref(f"{self.engine_name}:{order.id}")
                argv, new_ref = self.engine.build_command(
                    self.system_prompt, prompt, f"wo-{order.id}", ref,
                    json_audit=self.json_audit)

                rc, raw_events, run_err = self._agent_pass(argv, wt.path)
                # hosts that pick their own session id (opencode) surface it here
                new_ref = new_ref or self.engine.ref_from_output(raw_events)
                if new_ref:
                    self.sessions.set_ref(f"{self.engine_name}:{order.id}", new_ref)
                report = (self.engine.extract_report(raw_events)
                          if self.json_audit else raw_events)
                secs = int(time.monotonic() - started)

                self._sweep(order.id, order.branch, wt.path)

                if rc == 0 and self.qa_enabled:
                    qa_rc, qa_raw, qa_report = self._qa_pass(
                        order, wt.path, branch=order.branch, base=base)

            return self._bookkeep(order, repo, new_status="review" if rc == 0
                                  else "blocked", report=report,
                                  run_err=run_err, rc=rc, secs=secs,
                                  raw_events=raw_events, qa_rc=qa_rc,
                                  qa_raw=qa_raw, qa_report=qa_report)

    def _agent_pass(self, argv: list[str], cwd: Path) -> tuple[int, str, str]:
        """One headless engine pass. Output is captured outside any working
        tree: anything written there could be swept onto a branch and vanish
        with a later checkout. Returns (rc, raw_stdout, stderr)."""
        rc, raw, run_err = 0, "", ""
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out"
            err_path = Path(tmp) / "err.log"
            try:
                with out_path.open("w") as out, err_path.open("w") as err:
                    proc = subprocess.run(argv, cwd=cwd, stdout=out,
                                          stderr=err, timeout=self.timeout_secs)
                    rc = proc.returncode
            except subprocess.TimeoutExpired:
                rc = 124
            except FileNotFoundError:
                factory.die(f"engine executable not found: {self.engine.binary} "
                            f"(set {self.engine.name.upper()}_BIN)", 127)
            raw = out_path.read_text()
            run_err = err_path.read_text()
        return rc, raw, run_err

    def _sweep(self, order_id: str, branch: str, wt_path: Path) -> None:
        """The agent must leave a committed branch; sweep up what it forgot."""
        if not factory.clean_tree(wt_path):
            factory.git(wt_path, "add", "-A")
            factory.git(wt_path, "commit", "-q", "-m",
                        f"wo-{order_id}: night-shift WIP (auto-committed by runner)")
            print(f"note: uncommitted work was auto-committed to {branch}")

    def _qa_pass(self, order: factory.WorkOrder, wt_path: Path,
                 branch: str, base: str) -> tuple[int, str, str]:
        """Advisory second pass: verify, don't trust. Returns (rc, raw, report)."""
        prompt = (f"QA pre-shift for work order {order.id}: the night shift "
                  f"implemented it on branch {branch}, checked out here. "
                  f"Review it against {base}. Follow the QA manual.\n\n"
                  f"# Work order {order.id}\n\n{order.path.read_text()}")
        ref = self.sessions.ref(f"{self.engine_name}:qa:{order.id}")
        argv, new_ref = self.engine.build_command(
            self.qa_system_prompt, prompt, f"qa-{order.id}", ref,
            json_audit=self.json_audit)
        print(f"QA pre-shift reviewing wo-{order.id} ...")
        rc, raw, _ = self._agent_pass(argv, wt_path)
        new_ref = new_ref or self.engine.ref_from_output(raw)
        if new_ref:
            self.sessions.set_ref(f"{self.engine_name}:qa:{order.id}", new_ref)
        report = self.engine.extract_report(raw) if self.json_audit else raw
        print(f"QA pre-shift done (exit {rc})")
        return rc, raw, report

    # ------------------------------------------------------- bookkeeping

    def _lint_block(self, order: factory.WorkOrder,
                    problems: list[str]) -> str:
        print(f"\n=== wo-{order.id} : {order.rel}  ->  BLOCKED by lint ===")
        for p in problems:
            print(f"  - {p}")
        report = ("**Status** — BLOCKED (by lint, before the agent started)\n\n"
                  + "\n".join(f"- {p}" for p in problems))
        order.append(f"\n### {datetime.now():%Y-%m-%d %H:%M} — blocked by lint\n\n")
        order.append(report)
        order.set_status("blocked")
        factory.git(self.root, "add", str(order.rel), "night-shift/logs")
        factory.git(self.root, "commit", "-q", "-m",
                    f"night-shift: wo-{order.id} -> blocked (lint)")
        print(f"wo-{order.id} -> blocked (lint)")
        return "blocked"

    def _bookkeep(self, order: factory.WorkOrder, repo: factory.TargetRepo,
                  new_status: str, report: str, run_err: str, rc: int,
                  secs: int, raw_events: str, qa_rc: int | None,
                  qa_raw: str, qa_report: str) -> str:
        outfile = self.logs / f"{self.today}-wo-{order.id}.out.md"
        errfile = self.logs / f"{self.today}-wo-{order.id}.err.log"
        outfile.write_text(report)
        errfile.write_text("" if rc == 0 else run_err)
        if self.json_audit:
            (self.logs / f"{self.today}-wo-{order.id}.events.jsonl"
             ).write_text(raw_events)
        if qa_raw:
            (self.logs / f"{self.today}-wo-{order.id}.qa.jsonl").write_text(qa_raw)

        order.append(f"\n### {datetime.now():%Y-%m-%d %H:%M} — night run "
                     f"(engine {self.engine_name}, target {repo.display()}), "
                     f"exit {rc} ({secs}s)\n\n")
        order.append(report)
        if rc != 0:
            order.append(f"\n> run FAILED (exit {rc}). "
                         f"stderr: {errfile.relative_to(self.root)}\n")
        if qa_rc is not None:
            order.append(f"\n---\n\n### QA pre-shift "
                         f"(engine {self.engine_name}, exit {qa_rc})\n\n")
            order.append(qa_report or "(empty QA report)")

        order.set_status(new_status)

        qa_note = f", qa exit {qa_rc}" if qa_rc is not None else ""
        with self.run_log.open("a") as f:
            f.write(f"\n## {datetime.now():%H:%M} run\n")
            f.write(f"- wo-{order.id} ({order.rel}) -> {repo.display()}: "
                    f"{new_status}, engine {self.engine_name}, exit {rc}{qa_note}, "
                    f"{secs}s — report in order file; "
                    f"raw: {outfile.relative_to(self.root)}\n")

        add_paths = [str(order.rel), "night-shift/logs"]
        if (self.root / "night-shift" / "sessions.json").exists():
            add_paths.append("night-shift/sessions.json")
        factory.git(self.root, "add", *add_paths)
        factory.git(self.root, "commit", "-q", "-m",
                    f"night-shift: wo-{order.id} -> {new_status} "
                    f"(exit {rc}, {secs}s)")

        print(f"wo-{order.id} -> {new_status} "
              f"({secs // 60}m{secs % 60:02d}s)")
        return new_status

    # ------------------------------------------------------------- helpers

    def _wpath(self, repo: factory.TargetRepo, order_id: str) -> Path:
        return self.worktrees / repo.slug() / f"wo-{order_id}"


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

    timeout_secs = int(os.environ.get("NIGHT_TIMEOUT_SECS", "7200"))
    root = factory.repo_root()
    if not (root / "work-orders").is_dir():
        factory.die("no work-orders/ directory — this is not a factory floor")
    if (branch := factory.git_out(root, "branch", "--show-current")) != "main":
        factory.die(f"start the night shift from main (you are on: {branch})")
    if not factory.clean_tree(root):
        factory.die("working tree must be clean before the night shift (commit or stash)")

    locks = root / "night-shift" / "locks"
    with factory.Lock(locks, "factory", f"factory checkout {root}"):
        NightRun(root, args.engine, args.repo, args.max_orders,
                 args.dry_run, timeout_secs).run()


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        print(e, file=sys.stderr)
        sys.exit(e.code)
