"""moonlighting init — verify the nWave guard, then set up the user
config and data dirs. When the guard is missing, init offers the official
install (uv or pipx) and lets the user decide. Installing the guard per
host stays outside this tool: nwave-ai install --platform <host>. Safe
to rerun.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile

from rich.console import Console

from . import factory, schedule

console = Console()

STARTER_CONFIG = """\
# moonlighting config — see the README for every key.
[factory]
engine = "pi"
"""


INSTALL_URL = ("https://raw.githubusercontent.com/nWave-ai/nWave/main/"
               "scripts/install/install.sh")
INSTALL_CMD = f'sh -c "$(curl -fsSL {INSTALL_URL})"'
NWAVE_HINT = (f"[yellow]nwave-ai is not installed. The night runs under "
              f"the nWave guard. Install it with:\n  {INSTALL_CMD}\n"
              f"Then rerun: moonlighting init[/yellow]")


def _run_nwave_bootstrap() -> bool:
    """Download the official nWave bootstrap script, then run it with sh.
    Two literal argv steps, no shell string, no shell=True."""
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        script = f.name
    try:
        dl = subprocess.run(["curl", "-fsSL", INSTALL_URL, "-o", script])
        if dl.returncode != 0:
            console.print("[red]download failed[/red]")
            return False
        console.print(f"[dim]$ sh {script}   # from {INSTALL_URL}[/dim]")
        r = subprocess.run(["sh", script])
        return r.returncode == 0
    finally:
        with contextlib.suppress(OSError):
            os.unlink(script)


def _check_nwave() -> None:
    """Verify nwave-ai, offering the official install script when
    missing. The user decides; init never installs without a yes."""
    nwave = shutil.which("nwave-ai")
    if nwave:
        console.print(f"[green]nwave-ai found[/green] {nwave}")
        return
    if not sys.stdin.isatty():
        console.print(NWAVE_HINT)
        return
    answer = input("nwave-ai is not installed. Run the official install "
                   "script now? [y/N] ")
    if answer.strip().lower() not in ("y", "yes"):
        console.print("skipped. Install it later, then rerun: "
                      "moonlighting init")
        return
    if _run_nwave_bootstrap() and shutil.which("nwave-ai"):
        console.print("[green]nwave-ai installed[/green]")
    else:
        console.print("[yellow]nwave-ai is still not on PATH. Open a new "
                      "shell, install it by hand, then rerun: "
                      "moonlighting init[/yellow]")


def main() -> None:
    console.print("[bold]moonlighting init[/bold]")

    _check_nwave()

    cfg = factory.config_path()
    if cfg.is_file():
        console.print(f"[green]config exists[/green] {cfg}")
    else:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(STARTER_CONFIG)
        console.print(f"[green]config created[/green] {cfg}")

    data = factory.data_dir()
    for sub in ("orders", "logs"):
        (data / sub).mkdir(parents=True, exist_ok=True)
    console.print(f"[green]data directory ready[/green] {data}")

    if sys.stdin.isatty():
        answer = input("Install the nightly cron (00:01, idle nights cost "
                       "nothing)? [y/N] ")
        if answer.strip().lower() in ("y", "yes"):
            schedule.install_cron()
    else:
        console.print("non-interactive: add the cron later with "
                      "`moonlighting schedule install`")

    console.print("next steps:")
    console.print(f"  edit the config: {cfg}")
    console.print('  create an order: moonlighting new-order "Title"')
    console.print("  try a night: moonlighting night --dry-run")
    console.print("  schedule nights: moonlighting schedule install")


if __name__ == "__main__":
    main()
