"""moonlighting init — report the bundled nWave guard, then set up the
user config and data dirs. Installing the guard per host stays manual:
nwave-ai install --platform <host>, then nwave-ai mode all. Safe to
rerun.
"""

from __future__ import annotations

import sys
from importlib import metadata

from rich.console import Console

from . import factory, schedule

console = Console()

STARTER_CONFIG = """\
# moonlighting config — see the README for every key.
[factory]
engine = "pi"
"""


def main() -> None:
    console.print("[bold]moonlighting init[/bold]")

    try:
        version = metadata.version("nwave-ai")
        console.print(f"[green]nwave-ai bundled[/green] v{version}")
        console.print("per-host install stays manual: nwave-ai install "
                      "--platform <host>, then: nwave-ai mode all")
    except metadata.PackageNotFoundError:
        console.print("[yellow]nwave-ai is missing from this environment. "
                      "Reinstall this package: uv tool upgrade "
                      "moonlighting-factory[/yellow]")

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
