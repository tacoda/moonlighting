"""Pytest bootstrap: every test runs against an isolated data directory
and user config. No test touches the real user state."""

import pytest


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("MOONLIGHTING_DATA", str(tmp_path_factory.mktemp("data")))
    cfg_dir = tmp_path_factory.mktemp("usercfg")
    monkeypatch.setenv("MOONLIGHTING_CONFIG", str(cfg_dir / "config.toml"))
