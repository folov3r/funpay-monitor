"""Desktop entrypoint: run the local API with a SQLite database.

Tauri starts this module as a sidecar. The same process also serves the web UI
when it is opened in a browser, so both interfaces share one backend.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import uvicorn

from app.api.app import create_app
from app.config import get_settings
from app.logging import setup_logging

logger = logging.getLogger(__name__)


def resolve_data_dir(explicit: str | None = None) -> Path:
    """Return the per-user directory that stores the SQLite file."""
    if explicit:
        return Path(explicit).expanduser()

    configured = os.getenv("FUNPAY_DATA_DIR") or get_settings().data_dir
    if configured:
        return Path(configured).expanduser()

    if sys.platform == "win32":
        base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "FunPayMonitor"

    xdg = os.getenv("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "funpay-monitor"


def database_path(data_dir: Path) -> Path:
    return data_dir / "funpay-monitor.sqlite3"


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the FunPay Monitor local API")
    parser.add_argument("--host", default=settings.api_host)
    parser.add_argument("--port", type=int, default=settings.api_port)
    parser.add_argument("--data-dir", default=None, help="override the SQLite directory")
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="serve the API without the background parse job",
    )
    args = parser.parse_args(argv)

    setup_logging(settings.log_level)
    data_dir = resolve_data_dir(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = database_path(data_dir)
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    logger.info("SQLite database: %s", db_path)
    logger.info("Listening on http://%s:%s", args.host, args.port)

    app = create_app(
        database_url=database_url,
        enable_scheduler=not args.no_scheduler,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
