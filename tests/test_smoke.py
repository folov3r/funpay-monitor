import importlib

import app


def test_version() -> None:
    assert app.__version__ == "0.1.0"


def test_entrypoint_modules_import() -> None:
    for module in ("app.config", "app.logging", "app.main", "app.worker"):
        assert importlib.import_module(module) is not None
