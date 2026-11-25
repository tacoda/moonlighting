"""moonlighting init — set up the nWave guard, user config and data dirs.

Order matters: install the nWave guard first, then this package. Init
brings both together and is safe to rerun.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from rich.console import Console

from . import factory, schedule

console = Console()

PLATFORMS = {"pi": "pi", "claude": "claude-code", "opencode": "opencode"}

STARTER_CONFIG = """\
# moonlighting config — see the README for every key.
[factory]
engine = "pi"
"""


def _run(cmd: list[str]) -> bool:
    """Run a setup step with inherited stdio. Installer prompts and
    progress stay visible, so a slow install never looks like a hang."""
    console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    r = subprocess.run(cmd)
    if r.returncode == 0:
        console.print("[green]ok[/green]")
        return True
    console.print(f"[red]failed (exit {r.returncode})[/red]")
    return False


def main() -> None:
    console.print("[bold]moonlighting init[/bold]")
    hosts = [name for name in PLATFORMS if shutil.which(name)]
    console.print(f"hosts found: {', '.join(hosts) or 'none'}")

    if shutil.which("nwave-ai"):
        for host in hosts:
            console.print(f"installing the nWave guard for {host} ...")
            _run(["nwave-ai", "install", "--platform", PLATFORMS[host]])
        console.print("activating the guard for every host ...")
        if _run(["nwave-ai", "mode", "all"]):
            console.print("guard active. Revert with: nwave-ai mode opt-in")
    else:
        console.print("[yellow]nwave-ai not found. Install the nWave guard "
                      "first, then rerun: moonlighting init[/yellow]")

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
