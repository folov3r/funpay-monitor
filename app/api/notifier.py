"""Desktop delivery channel: system notification plus the in-app history."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys

from app.services.alerts import PendingAlert, format_alert_text

logger = logging.getLogger(__name__)


async def send_system_notification(title: str, body: str) -> bool:
    """Show a native notification when the platform helper is available.

    Linux uses ``notify-send`` (libnotify). Windows uses ``winotify`` when it is
    installed; otherwise the alert is only written to the log and the in-app
    history, which the Tauri shell reads through the API.
    """
    if sys.platform.startswith("linux") and shutil.which("notify-send"):
        try:
            process = await asyncio.create_subprocess_exec(
                "notify-send",
                "--app-name=FunPay Monitor",
                title,
                body,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=5)
            return process.returncode == 0
        except (OSError, TimeoutError):
            logger.exception("notify-send failed")
            return False

    if sys.platform == "win32":
        try:
            from winotify import Notification  # type: ignore[import-not-found]
        except ImportError:
            logger.info("winotify is not installed; notification stays in-app")
            return False
        try:
            await asyncio.to_thread(
                Notification(app_id="FunPay Monitor", title=title, msg=body).show
            )
            return True
        except Exception:
            logger.exception("Windows toast failed")
            return False

    logger.info("System notifications are not supported on %s", sys.platform)
    return False


class DesktopAlertNotifier:
    """Send alerts to the desktop and keep them in the notification table."""

    async def send(self, alert: PendingAlert, *, chart: bytes | None = None) -> None:
        title = f"FunPay Monitor · {alert.category_title}"
        body = format_alert_text(alert)
        logger.info("Alert #%s: %s", alert.subscription_id, body.replace("\n", " | "))
        await send_system_notification(title, body)
