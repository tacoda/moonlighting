"""Shared helpers for the moonlighting factory scripts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def repo_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        die("not inside a git repository")
    return Path(out)


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=check
    )


def git_out(root: Path, *args: str) -> str:
    return git(root, *args).stdout.strip()


def clean_tree(root: Path) -> bool:
    return git_out(root, "status", "--porcelain") == ""


def parse_order(path: Path) -> dict[str, str]:
    """Parse the YAML-ish frontmatter of a work order (key: value lines)."""
    fields: dict[str, str] = {}
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return fields
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def set_status(path: Path, new_status: str) -> None:
    """Rewrite the status line — but only inside the frontmatter."""
    lines = path.read_text().splitlines()
    in_fm = False
    for i, line in enumerate(lines):
        if line.strip() == "---":
            in_fm = not in_fm
            continue
        if in_fm and line.startswith("status:"):
            lines[i] = f"status: {new_status}"
            break
    path.write_text("\n".join(lines) + "\n")
