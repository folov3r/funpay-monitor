"""Tests for the desktop entrypoint helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.desktop import database_path, resolve_data_dir


def test_explicit_data_dir_wins(tmp_path: Path) -> None:
    assert resolve_data_dir(str(tmp_path)) == tmp_path


def test_funpay_data_dir_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FUNPAY_DATA_DIR", str(tmp_path))
    assert resolve_data_dir() == tmp_path


def test_linux_default_uses_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FUNPAY_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("app.desktop.sys.platform", "linux")
    assert resolve_data_dir() == tmp_path / "funpay-monitor"


def test_windows_default_uses_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FUNPAY_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr("app.desktop.sys.platform", "win32")
    assert resolve_data_dir() == tmp_path / "FunPayMonitor"


def test_database_path_is_inside_data_dir(tmp_path: Path) -> None:
    assert database_path(tmp_path) == tmp_path / "funpay-monitor.sqlite3"
