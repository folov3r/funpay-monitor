import importlib
import tomllib
from pathlib import Path

import app

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_matches_pyproject() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert app.__version__ == project["version"]


def test_entrypoint_modules_import() -> None:
    for module in ("app.config", "app.logging", "app.main", "app.worker", "app.desktop"):
        assert importlib.import_module(module) is not None
