"""Pytest bootstrap: tests run in dev mode with an isolated user config."""

import pytest


@pytest.fixture(autouse=True)
def dev_mode_and_isolated_config(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("MOONLIGHTING_DEV", "1")
    cfg_dir = tmp_path_factory.mktemp("usercfg")
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg_dir / "config.toml"))
