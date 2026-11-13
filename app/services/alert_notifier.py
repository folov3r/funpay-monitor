"""VK delivery channel for price alerts."""

from __future__ import annotations

import logging
import random
from typing import Any

from app.services.alerts import PendingAlert, format_alert_text
from app.services.vk_upload import upload_message_photo

logger = logging.getLogger(__name__)


class VkAlertNotifier:
    """Send alerts to users through a VK community token."""

    def __init__(self, api: Any) -> None:
        self._api = api

    async def send(self, alert: PendingAlert, *, chart: bytes | None = None) -> None:
        attachment: str | None = None
        if chart:
            try:
                attachment = await upload_message_photo(
                    self._api,
                    alert.user_vk_id,
                    chart,
                )
            except Exception:
                logger.exception(
                    "Chart upload failed for alert #%s, sending text only",
                    alert.subscription_id,
                )

        await self._api.messages.send(
            peer_id=alert.user_vk_id,
            message=format_alert_text(alert),
            attachment=attachment,
            random_id=random.randint(1, 2**31 - 1),
        )
