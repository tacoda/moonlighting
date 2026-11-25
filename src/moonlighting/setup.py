"""moonlighting init — set up the nWave guard, user config and data dirs.

Order matters: install the nWave guard first, then this package. Init
brings both together and is safe to rerun.
"""

from __future__ import annotations

import shutil
import subprocess

from rich.console import Console

from . import factory

console = Console()

PLATFORMS = {"pi": "pi", "claude": "claude-code", "opencode": "opencode"}

STARTER_CONFIG = """\
# moonlighting config. Full sample: docs/config-sample.toml
[factory]
engine = "pi"
"""


def _run(cmd: list[str]) -> bool:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        console.print(f"[green]ok[/green] {' '.join(cmd)}")
        return True
    console.print(f"[red]failed[/red] {' '.join(cmd)}")
    for stream in (r.stdout, r.stderr):
        if stream.strip():
            console.print(stream.strip())
    return False


def main() -> None:
    console.print("[bold]moonlighting init[/bold]")
    hosts = [name for name in PLATFORMS if shutil.which(name)]
    console.print(f"hosts found: {', '.join(hosts) or 'none'}")

    if shutil.which("nwave-ai"):
        for host in hosts:
            _run(["nwave-ai", "install", "--platform", PLATFORMS[host]])
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

    console.print("next steps:")
    console.print(f"  edit the config: {cfg}")
    console.print('  create an order: moonlighting new-order "Title"')
    console.print("  try a night: moonlighting night --dry-run")
    console.print("  schedule nights: moonlighting schedule install")


if __name__ == "__main__":
    main()
