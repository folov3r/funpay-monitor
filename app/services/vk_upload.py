"""Upload images to VK so they can be attached to community messages."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class VkUploadError(RuntimeError):
    """Raised when VK returns an incomplete upload response."""


async def upload_message_photo(
    api: Any,
    peer_id: int,
    image: bytes,
    *,
    filename: str = "chart.png",
    client: httpx.AsyncClient | None = None,
) -> str:
    """Upload PNG bytes to VK and return an attachment string.

    The returned value is ready for ``messages.send`` / ``Message.answer``:
    ``photo{owner_id}_{id}``.
    """
    server = await api.photos.get_messages_upload_server(peer_id=peer_id)
    upload_url = getattr(server, "upload_url", None)
    if not upload_url:
        raise VkUploadError("VK did not return an upload URL")

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await http.post(
            upload_url,
            files={"photo": (filename, image, "image/png")},
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            await http.aclose()

    photo = payload.get("photo")
    server_value = payload.get("server")
    if not photo or server_value is None:
        logger.error("Unexpected VK photo upload response: %s", payload)
        raise VkUploadError("VK photo upload returned no photo/server")

    saved = await api.photos.save_messages_photo(
        photo=photo,
        hash=payload.get("hash"),
        server=server_value,
    )
    if not saved:
        raise VkUploadError("VK did not save the uploaded photo")

    first = saved[0]
    return f"photo{first.owner_id}_{first.id}"
