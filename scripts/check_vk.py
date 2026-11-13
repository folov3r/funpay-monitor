"""Check the VK community token before starting the bot and worker.

Usage:
    python scripts/check_vk.py
"""

from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from vkbottle import API


async def main() -> int:
    settings = get_settings()
    if not settings.vk_group_token:
        print("VK_GROUP_TOKEN is empty: fill .env before running the bot")
        return 1
    if not settings.vk_group_id:
        print("VK_GROUP_ID is empty: set the community id in .env")
        return 1

    api = API(settings.vk_group_token)
    try:
        groups = await api.groups.get_by_id(group_id=settings.vk_group_id)
        if groups:
            group = groups[0]
            print(f"Community: {group.name} (id {group.id})")
            print(f"Screen name: {group.screen_name}")

        server = await api.groups.get_long_poll_server(group_id=settings.vk_group_id)
        print(f"Long Poll server: {server.server}")
        print("Token works: bot and worker can start")
    except Exception as exc:
        print(f"VK check failed: {exc}")
        return 1
    finally:
        await api.http_client.close()

    admins = settings.admin_vk_ids()
    print(f"Admins configured: {len(admins)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
