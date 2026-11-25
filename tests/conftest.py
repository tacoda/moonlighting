"""Pytest bootstrap: tests run with an isolated user config.

The autouse fixture points MOONLIGHTING_CONFIG at a nonexistent file, so
tests never read the real ~/.config/moonlighting/config.toml.
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_user_config(tmp_path_factory, monkeypatch):
    cfg_dir = tmp_path_factory.mktemp("usercfg")
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg_dir / "config.toml"))
