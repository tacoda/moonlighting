#!/usr/bin/env python3
"""moonlighting night — execute approved work orders headlessly.

Each order names its target repo via the `repo:` frontmatter field (a
config binding name, a path, or a git URL — URLs are cloned under the data
directory). The agent works on the order's branch inside a throwaway git
worktree, so the target's own working copy is never switched or touched.
The runner keeps status flips and logs under the data directory.

Run one night process per target repo — locks make double-running visible.
See docs/runbook.md.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import factory

PLAN_SYSTEM = ("You are the planning pass of a night shift. Read the work "
               "order and reply with a short implementation plan: the "
               "approach, the files to change, and the risks. Do not write "
               "code. A builder follows your plan next.")


class NightRun:
    """One night shift: collect the approved queue, execute it under locks,
    bookkeep in the factory repo."""

    def __init__(self, fl: dict, engine_name: str | None,
                 repo_filter: str | None,
                 max_orders: int, dry_run: bool, timeout_secs: int,
                 model: str | None = None, qa_model: str | None = None,
                 plan_model: str | None = None):
        self.fl = fl
        self.flag_engine = engine_name
        self.flag_model = model
        self.flag_qa_model = qa_model
        self.flag_plan_model = plan_model
        self.env_engine = os.environ.get("FACTORY_ENGINE")
        self.env_model = os.environ.get("FACTORY_MODEL")
        self.env_qa_model = os.environ.get("FACTORY_QA_MODEL")
        self.env_plan_model = os.environ.get("FACTORY_PLAN_MODEL")
        cfg = factory.load_config().get("factory", {})
        self.cfg_engine = cfg.get("engine")
        self.cfg_model = cfg.get("model")
        self.cfg_qa_model = cfg.get("qa-model")
        self.cfg_plan_model = cfg.get("plan-model")
        self.plan_enabled = os.environ.get("FACTORY_PLAN", "1") != "0"
        self.engine_name = (self.flag_engine or self.env_engine
                            or self.cfg_engine)
        self.model = self.flag_model or self.env_model or self.cfg_model
        self.qa_model = (self.flag_qa_model or self.env_qa_model
                         or self.cfg_qa_model)
        self.orders = fl["orders"]
        self.dry_run = dry_run
        self.update = not dry_run
        self.repo_filter = (factory.TargetRepo.resolve(repo_filter,
                                                       update=self.update)
                            if repo_filter else None)
        if repo_filter and self.repo_filter is None:
            factory.die(f"cannot resolve --repo: {repo_filter}")
        self.max_orders = max_orders
        self.timeout_secs = timeout_secs

        self.logs = fl["logs"]
        self.logs.mkdir(parents=True, exist_ok=True)
        self.today = f"{datetime.now():%Y-%m-%d}"
        self.run_log = self.logs / f"{self.today}.md"
        self.worktrees = fl["worktrees"]
        self.sessions = factory.SessionStore(fl["sessions"])
        self.system_prompt = fl["manual"].read_text()
        self.qa_system_prompt = fl["qa"].read_text()
        self.json_audit = os.environ.get("FACTORY_JSON_AUDIT", "1") != "0"
        self.qa_enabled = os.environ.get("FACTORY_QA", "1") != "0"

    # ------------------------------------------------------------ queue

    def collect(self) -> tuple[list, list, int]:
        """Returns (healthy orders with repos, problem orders with reasons,
        and the count skipped under --repo). Problem orders carry no repo,
        so a --repo filter skips them instead of guessing."""
        healthy: list = []
        problems: list = []
        skipped = 0
        for path in sorted(self.orders.glob("*.md")):
            order = factory.WorkOrder(path)
            if order.status != "approved":
                continue
            trouble: list[str] = order.lint()
            repo = None
            if not trouble and not order.repo_value:
                trouble = ["repo: this order names no target repo — bind it "
                           "in the config or set repo: <path-or-url>"]
            elif not trouble:
                repo = factory.TargetRepo.resolve(order.repo_value,
                                                  update=self.update, soft=True)
                if repo is None:
                    # soft resolve. The clone failed or the path is not a
                    # git repo. Block this order instead of aborting.
                    trouble = ["repo: unresolvable (clone failed or not a "
                               "git repository)"]
            if trouble:
                if self.repo_filter is not None:
                    skipped += 1
                else:
                    problems.append((order, trouble))
                continue
            if (self.repo_filter is not None
                    and (repo is None or repo.path != self.repo_filter.path)):
                continue
            healthy.append((order, repo))
        return healthy, problems, skipped

    # ------------------------------------------------------------ the run

    def run(self) -> None:
        healthy, problems, skipped = self.collect()
        if not healthy and not problems:
            if self.repo_filter is None:
                print("nothing approved — nothing to do tonight.")
                return
            print("nothing approved for this repo — nothing to do tonight.")
            others = []
            for path in sorted(self.orders.glob("*.md")):
                order = factory.WorkOrder(path)
                if order.status != "approved":
                    continue
                target = order.repo_value or "(no target repo)"
                others.append(f"  {order.id}  {order.title}  ->  {target}")
            if others:
                print("approved orders exist for other repos:")
                for line in others:
                    print(line)
            return

        print("night shift queue:")
        for order, repo in healthy:
            print(f"  {order.rel}  ->  {repo.display()}")
        for order, trouble in problems:
            print(f"  {order.rel}  ->  BLOCKED before the run "
                  f"({len(trouble)} problem(s))")
        if self.dry_run:
            return
        if skipped:
            print(f"{skipped} malformed approved order(s) skipped under "
                  f"--repo — run without --repo to block them")

        # lint blocks cost no tokens and stop nothing: block them all
        # before running the healthy queue
        blocked: list[str] = []
        for order, trouble in problems:
            self._block_order(order, trouble)
            blocked.append(order.id)

        ran = 0
        failed: str | None = None
        for order, repo in healthy:
            if ran >= self.max_orders:
                break
            new_status = self._process(order, repo)
            ran += 1
            if new_status == "blocked":
                failed = order.id
                break

        self._write_morning_digest()

        print(f"\nnight shift over: {ran} order(s) processed"
              + (f", {len(blocked)} blocked by lint" if blocked else "") + ".")
        if failed:
            print(f"wo-{failed} is blocked — run stopped. See {self.run_log}")
        print("morning: moonlighting status")

    # ------------------------------------------------------- per-order flow

    def _process(self, order: factory.WorkOrder,
                 repo: factory.TargetRepo) -> str:
        print(f"\n=== wo-{order.id} : {order.rel}  ->  {repo.display()} ===")

        # the night runs in a throwaway worktree of the target repo, under a
        # lock; the target's own working copy is never switched
        with factory.Lock(self.fl["locks"],
                          repo.slug(), f"repo {repo.display()}"):
            started = time.monotonic()
            rc, report, raw_events, run_err, secs = 0, "", "", "", 0
            qa_rc, qa_raw, qa_report, qa_moved = None, "", "", False
            no_commits = False

            if repo.is_dirty():
                print(f"note: {repo.display()} has uncommitted changes — "
                      f"isolated from the night (it runs in a worktree)")
            base = repo.base_ref()
            repo_env = repo.env()
            engine_name, model, qa_model, plan_model = self._harness_for(
                order, repo)
            engine = factory.engine(engine_name)
            with factory.Worktree(repo, self._wpath(repo, order.id),
                                  order.branch, base) as wt:
                prompt = (f"Execute work order {order.id} now, following the "
                          f"night-shift manual in your system prompt.\n\n"
                          f"# Work order {order.id}\n\n{order.path.read_text()}")
                plan_rc = None
                plan_report = ""
                if self.plan_enabled and plan_model:
                    print(f"planning pass on wo-{order.id} "
                          f"(model {plan_model}) ...")
                    plan_prompt = (
                        f"Plan the implementation of work order {order.id}. "
                        f"Do not write code. Reply with a short plan: the "
                        f"approach, the files to change, and the risks.\n\n"
                        f"# Work order {order.id}\n\n{order.path.read_text()}")
                    plan_ref = self.sessions.ref(
                        f"{engine_name}:plan:{order.id}")
                    pargv, pref, pstdin = engine.build_command(
                        PLAN_SYSTEM, plan_prompt, f"plan-{order.id}",
                        plan_ref, json_audit=self.json_audit,
                        model=plan_model)
                    plan_rc, plan_raw, plan_err = self._agent_pass(
                        pargv, wt.path, engine, pstdin, env_extra=repo_env)
                    new_plan_ref = pref or engine.ref_from_output(plan_raw)
                    if new_plan_ref:
                        self.sessions.set_ref(
                            f"{engine_name}:plan:{order.id}", new_plan_ref)
                    plan_report = (engine.extract_report(plan_raw)
                                   if self.json_audit else plan_raw)
                    # the planner may touch the tree: reset it, so the
                    # builder starts clean
                    factory.git(wt.path, "reset", "--hard", base,
                                check=False)
                    factory.git(wt.path, "clean", "-fd", check=False)
                    if plan_rc == 0 and plan_report.strip():
                        prompt = (f"Execute work order {order.id} now. A "
                                  f"planning pass wrote the plan below. "
                                  f"Follow it where it helps.\n\n"
                                  f"# Implementation plan\n\n{plan_report}\n\n"
                                  f"# Work order {order.id}\n\n"
                                  f"{order.path.read_text()}")
                    else:
                        plan_report = ""
                        print(f"plan pass failed (exit {plan_rc}) — "
                              f"building without it")
                ref = self.sessions.ref(f"{engine_name}:{order.id}")
                argv, new_ref, stdin_text = engine.build_command(
                    self.system_prompt, prompt, f"wo-{order.id}", ref,
                    json_audit=self.json_audit, model=model)

                rc, raw_events, run_err = self._agent_pass(argv, wt.path,
                                                           engine, stdin_text,
                                                           env_extra=repo_env)
                # hosts that pick their own session id (opencode) surface it here
                new_ref = new_ref or engine.ref_from_output(raw_events)
                if new_ref:
                    self.sessions.set_ref(f"{engine_name}:{order.id}", new_ref)
                report = (engine.extract_report(raw_events)
                          if self.json_audit else raw_events)
                secs = int(time.monotonic() - started)

                self._sweep(order.id, order.branch, wt.path, repo)
                ahead = int(factory.git_out(wt.path, "rev-list", "--count",
                                            f"{base}..HEAD") or "0")
                no_commits = ahead == 0

                remaining = self.timeout_secs - int(time.monotonic() - started)
                if rc == 0 and not no_commits and self.qa_enabled:
                    qa_rc, qa_raw, qa_report, qa_moved = self._qa_pass(
                        order, wt.path, branch=order.branch, base=base,
                        model=model, qa_model=qa_model, engine=engine,
                        engine_name=engine_name,
                        timeout_secs=max(1, remaining))

            return self._bookkeep(order, repo,
                                  new_status="review" if rc == 0 and not no_commits
                                  else "blocked", report=report,
                                  run_err=run_err, rc=rc, secs=secs,
                                  raw_events=raw_events, qa_rc=qa_rc,
                                  qa_raw=qa_raw, qa_report=qa_report,
                                  qa_moved=qa_moved, no_commits=no_commits,
                                  model=model, engine_name=engine_name,
                                  plan_rc=plan_rc, plan_report=plan_report,
                                  plan_model=plan_model)

    def _agent_pass(self, argv: list[str], cwd: Path,
                    engine: factory.Engine,
                    stdin_text: str | None = None,
                    timeout_secs: int | None = None,
                    env_extra: dict[str, str] | None = None
                    ) -> tuple[int, str, str]:
        """One headless engine pass. Output is captured outside any working
        tree: anything written there could be swept onto a branch and vanish
        with a later checkout. Returns (rc, raw_stdout, stderr)."""
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out"
            err_path = Path(tmp) / "err.log"
            rc = factory.run_under_timeout(
                argv, cwd, timeout_secs or self.timeout_secs, out_path,
                err_path, input_text=stdin_text, env_extra=env_extra,
                not_found_hint=f"(set {engine.name.upper()}_BIN)")
            return rc, out_path.read_text(), err_path.read_text()

    def _sweep(self, order_id: str, branch: str, wt_path: Path,
               repo: factory.TargetRepo) -> None:
        """The agent must leave a committed branch; sweep up what it forgot."""
        if not factory.clean_tree(wt_path):
            env = repo.env()
            factory.git(wt_path, "add", "-A")
            factory.git(wt_path, "commit", "-q", "-m",
                        f"wo-{order_id}: WIP sweep (auto-committed by the runner)",
                        env=env)
            print(f"note: uncommitted work was auto-committed to {branch}")

    def _qa_pass(self, order: factory.WorkOrder, wt_path: Path,
                 branch: str, base: str, engine: factory.Engine,
                 model: str | None = None, qa_model: str | None = None,
                 engine_name: str | None = None,
                 timeout_secs: int | None = None,
                 env_extra: dict[str, str] | None = None
                 ) -> tuple[int, str, str, bool]:
        """Advisory second pass: verify, don't trust. The QA manual says
        read-only. The tip guard keeps the branch intact even when the QA
        model misbehaves. Returns (rc, raw, report, tip_moved)."""
        prompt = (f"QA pre-shift for work order {order.id}: the night shift "
                  f"implemented it on branch {branch}, checked out here. "
                  f"Review it against {base}. Follow the QA manual.\n\n"
                  f"# Work order {order.id}\n\n{order.path.read_text()}")
        ref = self.sessions.ref(f"{engine_name or self.engine_name}:qa:{order.id}")
        qa_model = qa_model or self.qa_model or model
        argv, new_ref, stdin_text = engine.build_command(
            self.qa_system_prompt, prompt, f"qa-{order.id}", ref,
            json_audit=self.json_audit, model=qa_model)
        print(f"QA pre-shift reviewing wo-{order.id} ...")
        tip_before = factory.git_out(wt_path, "rev-parse", "HEAD")
        rc, raw, _ = self._agent_pass(argv, wt_path, engine, stdin_text,
                                      timeout_secs=timeout_secs,
                                      env_extra=env_extra)
        new_ref = new_ref or engine.ref_from_output(raw)
        if new_ref:
            self.sessions.set_ref(f"{engine_name or self.engine_name}:qa:{order.id}", new_ref)
        moved = factory.git_out(wt_path, "rev-parse", "HEAD") != tip_before
        if moved:
            print(f"QA moved the branch tip on wo-{order.id} — resetting to "
                  f"the agent's tip")
            factory.git(wt_path, "reset", "--quiet", "--hard", tip_before)
        report = engine.extract_report(raw) if self.json_audit else raw
        print(f"QA pre-shift done (exit {rc})")
        return rc, raw, report, moved

    # ------------------------------------------------------- bookkeeping

    def _block_order(self, order: factory.WorkOrder,
                     problems: list[str]) -> None:
        """Block one malformed order. No commit here: the caller batches all
        lint blocks into one commit and keeps the night running."""
        print(f"\n=== wo-{order.id} : {order.rel}  ->  BLOCKED by lint ===")
        for p in problems:
            print(f"  - {p}")
        report = ("**Status** — BLOCKED (by lint, before the agent started)\n\n"
                  + "\n".join(f"- {p}" for p in problems))
        order.append(f"\n### {datetime.now():%Y-%m-%d %H:%M} — blocked by lint\n\n")
        order.append(report)
        order.set_status("blocked")
        with self.run_log.open("a") as f:
            f.write(f"\n## {datetime.now():%H:%M} lint-block\n")
            f.write(f"- wo-{order.id} ({order.rel}): blocked — "
                    f"{len(problems)} problem(s)\n")
        print(f"wo-{order.id} -> blocked (lint)")

    def _bookkeep(self, order: factory.WorkOrder, repo: factory.TargetRepo,
                  new_status: str, report: str, run_err: str, rc: int,
                  secs: int, raw_events: str, qa_rc: int | None,
                  qa_raw: str, qa_report: str, qa_moved: bool = False,
                  no_commits: bool = False, model: str | None = None,
                  engine_name: str | None = None,
                  plan_rc: int | None = None, plan_report: str = "",
                  plan_model: str | None = None) -> str:
        ename = engine_name or self.engine_name
        outfile = self.logs / f"{self.today}-wo-{order.id}.out.md"
        errfile = self.logs / f"{self.today}-wo-{order.id}.err.log"
        outfile.write_text(report)
        if run_err:
            errfile.write_text(run_err)
        if self.json_audit:
            (self.logs / f"{self.today}-wo-{order.id}.events.jsonl"
             ).write_text(raw_events)
        if qa_raw:
            (self.logs / f"{self.today}-wo-{order.id}.qa.jsonl").write_text(qa_raw)

        model_note = f", model {model}" if model else ""
        order.append(f"\n### {datetime.now():%Y-%m-%d %H:%M} — night run "
                     f"(engine {ename}{model_note}, "
                     f"target {repo.display()}), exit {rc} ({secs}s)\n\n")
        order.append(report)
        if no_commits:
            order.append("\n> the agent left no commits on the branch — "
                         "marked blocked, nothing to review\n")
        if rc != 0:
            note = f"\n> run FAILED (exit {rc})."
            if run_err:
                note += f" stderr: {errfile.name}\n"
            order.append(note + "\n")
        if plan_rc is not None:
            plan_model_note = f", model {plan_model}" if plan_model else ""
            order.append(f"\n---\n\n### planning pass (engine {ename}"
                         f"{plan_model_note}, exit {plan_rc})\n\n")
            order.append(plan_report or "(empty plan)")
        if qa_rc is not None:
            order.append(f"\n---\n\n### QA pre-shift "
                         f"(engine {ename}, exit {qa_rc})\n\n")
            order.append(qa_report or "(empty QA report)")
        if qa_moved:
            order.append("\n> the QA pass modified the branch. The runner "
                         "reset it to the agent's tip\n")

        order.set_status(new_status)

        qa_note = f", qa exit {qa_rc}" if qa_rc is not None else ""
        plan_note = f", plan exit {plan_rc}" if plan_rc is not None else ""
        with self.run_log.open("a") as f:
            f.write(f"\n## {datetime.now():%H:%M} run\n")
            f.write(f"- wo-{order.id} ({order.rel}) -> {repo.display()}: "
                    f"{new_status}, engine {ename}{model_note}, "
                    f"exit {rc}{plan_note}{qa_note}, "
                    f"{secs}s — report in order file; "
                    f"raw: {outfile.name}\n")

        print(f"wo-{order.id} -> {new_status} "
              f"({secs // 60}m{secs % 60:02d}s)")
        return new_status

    def _write_morning_digest(self) -> None:
        """One file the day shift reads first: every review and blocked
        order with its latest QA verdict."""
        rows = []
        for path in sorted(self.orders.glob("*.md")):
            order = factory.WorkOrder(path)
            if order.status not in ("review", "blocked"):
                continue
            qa = ""
            text = path.read_text()
            idx = text.rfind("### QA pre-shift")
            if idx >= 0:
                for line in text[idx:].splitlines()[1:]:
                    if line.strip():
                        qa = line.strip().lstrip("*- ").strip()
                        break
            rows.append(f"- {order.id} {order.title} — {order.status}"
                        + (f" (QA: {qa})" if qa else ""))
        if not rows:
            return
        stamp = f"{datetime.now():%Y-%m-%d %H:%M}"
        digest = self.logs / f"{self.today}-morning.md"
        digest.write_text(f"# morning digest — {stamp}\n\n"
                          + "\n".join(rows) + "\n")
        print(f"morning digest: {digest}")

    # ------------------------------------------------------------- helpers

    def _wpath(self, repo: factory.TargetRepo, order_id: str) -> Path:
        return self.worktrees / repo.slug() / f"wo-{order_id}"

    def _harness_for(self, order: factory.WorkOrder,
                     repo: factory.TargetRepo) -> tuple[str, str | None, str | None, str | None]:
        """Per-order harness. Precedence: the order frontmatter, then
        explicit flags, then the environment, then the repo binding, then
        the [factory] section. With none of these the order errors: no
        silent defaults. plan_model stays None when no plan-model resolves
        anywhere: the pass is skipped."""
        engine_name = (order.engine or self.flag_engine or self.env_engine
                       or repo.engine or self.cfg_engine)
        if not engine_name:
            factory.die(f"wo-{order.id}: no engine defined. Set engine in "
                        f"the order frontmatter, the repo binding or "
                        f"[factory]")
        model = (order.model or self.flag_model or self.env_model
                 or repo.model or self.cfg_model or None)
        qa_model = (order.qa_model or self.flag_qa_model or self.env_qa_model
                    or repo.qa_model or self.cfg_qa_model or model)
        plan_model = (order.plan_model or self.flag_plan_model
                      or self.env_plan_model or self.cfg_plan_model or None)
        return engine_name, model, qa_model, plan_model


def main() -> None:
    ap = argparse.ArgumentParser(description="Execute approved work orders (night shift).")
    cfg = factory.load_config().get("factory", {})
    try:
        max_default = int(cfg.get("max-orders") or 1)
    except (TypeError, ValueError):
        factory.die("config max-orders must be an integer", 2)
    ap.add_argument("--engine", default=None,
                    help="host agent: pi, claude, opencode, codex or any configured harness. "
                         "env FACTORY_ENGINE, or config [factory] engine")
    ap.add_argument("--model", default=None,
                    help="model string for the engine, passed verbatim "
                         "(host-specific syntax). env FACTORY_MODEL, or "
                         "config [factory] model")
    ap.add_argument("--plan-model", default=None, dest="plan_model",
                    help="model for the planning pass, which runs before "
                         "the builder when set. env FACTORY_PLAN_MODEL, or "
                         "config [factory] plan-model")
    ap.add_argument("--qa-model", default=None,
                    help="model for the QA pass. Falls back to the order "
                         "model. env FACTORY_QA_MODEL, or config "
                         "[factory] qa-model")
    ap.add_argument("--repo", default=cfg.get("repo") or None, metavar="REPO",
                    help="only process orders for this repo "
                         "(default: config repo)")
    ap.add_argument("--max-orders", type=int, default=max_default,
                    help="run at most N orders (default: config max-orders, "
                         "or 1)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would run, change nothing")
    args = ap.parse_args()

    try:
        timeout_secs = int(os.environ.get("NIGHT_TIMEOUT_SECS", "7200"))
    except ValueError:
        factory.die("NIGHT_TIMEOUT_SECS must be an integer (seconds)", 2)
    fl = factory.floor()
    orders = fl["orders"]
    if not orders.is_dir():
        factory.die(f"no work orders directory: {orders} — create it or set "
                    f"FACTORY_ORDERS_DIR")

    with factory.Lock(fl["locks"], "night", "the night shift"):
        NightRun(fl, args.engine, args.repo, args.max_orders,
                 args.dry_run, timeout_secs, args.model, args.qa_model,
                 args.plan_model).run()


if __name__ == "__main__":
    try:
        main()
    except factory.FactoryError as e:
        # Pre-flight failures leave nothing else behind. Give them a fixed,
        # gitignored home next to the run logs.
        with contextlib.suppress(Exception):
            log = factory.data_dir() / "logs" / "errors.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            stamp = f"{datetime.now():%Y-%m-%d %H:%M}"
            with log.open("a") as f:
                f.write(f"{stamp} exit {e.code}: {e}\n")
        print(e, file=sys.stderr)
        sys.exit(e.code)
