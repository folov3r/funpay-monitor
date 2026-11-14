"""Clean up the chat messages of the ``/add`` dialog after a successful save."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from vkbottle import API, VKAPIError

logger = logging.getLogger(__name__)

#: VK refuses to delete a message for everybody when the peer already removed
#: it or the community is not allowed to; the bot silently gives up on it.
CANNOT_DELETE_FOR_ALL = 924
#: ``messages.delete`` accepts up to 100 conversation message ids per call.
DELETE_BATCH_SIZE = 100
#: Upper bound of one dialog chain, so an abandoned dialog cannot grow forever.
MAX_TRACKED_MESSAGES = 200


class ChatCleaner:
    """Remember conversation ids of one dialog and delete them on success.

    Tracking lives in memory, exactly like the vkbottle state dispenser: a bot
    restart loses the chain, which is acceptable for the ``/add`` flow. The
    cleaner is intentionally not tied to the database — deleting chat history
    must never fail a subscription save.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        group_id: int = 0,
        max_messages: int = MAX_TRACKED_MESSAGES,
    ) -> None:
        self._enabled = enabled
        self._group_id = group_id or None
        self._max_messages = max_messages
        self._cmids: dict[int, list[int]] = {}

    @property
    def enabled(self) -> bool:
        """Whether messages are tracked and deleted at all."""
        return self._enabled

    def reset(self, peer_id: int) -> None:
        """Start a new dialog: forget whatever was tracked before."""
        self._cmids.pop(peer_id, None)

    def track(self, peer_id: int, cmids: Iterable[int | None]) -> None:
        """Remember dialog messages; ``None`` and duplicates are ignored."""
        if not self._enabled:
            return
        bucket = self._cmids.setdefault(peer_id, [])
        for cmid in cmids:
            if cmid is None or cmid in bucket:
                continue
            bucket.append(cmid)
        overflow = len(bucket) - self._max_messages
        if overflow > 0:
            del bucket[:overflow]

    def forget(self, peer_id: int) -> None:
        """Drop the tracked chain without deleting anything."""
        self._cmids.pop(peer_id, None)

    def tracked(self, peer_id: int) -> list[int]:
        """Return a copy of the tracked conversation ids of a dialog."""
        return list(self._cmids.get(peer_id, ()))

    async def purge(self, api: API, peer_id: int, *, keep: Iterable[int] = ()) -> int:
        """Delete tracked dialog messages except ``keep``; return deleted count."""
        cmids = self._cmids.pop(peer_id, [])
        if not self._enabled or not cmids:
            return 0
        kept = set(keep)
        targets = [cmid for cmid in cmids if cmid not in kept]
        deleted = 0
        for start in range(0, len(targets), DELETE_BATCH_SIZE):
            batch = targets[start : start + DELETE_BATCH_SIZE]
            deleted += await self._delete_batch(api, peer_id, batch)
        return deleted

    async def _delete_batch(self, api: API, peer_id: int, cmids: list[int]) -> int:
        try:
            await self._delete(api, peer_id, cmids)
            return len(cmids)
        except VKAPIError as error:
            if error.code != CANNOT_DELETE_FOR_ALL:
                logger.warning("Could not delete dialog messages in peer %s: %s", peer_id, error)
                return 0
        except Exception:  # pragma: no cover - network failure must not break /add
            logger.exception("Unexpected error while deleting dialog messages in peer %s", peer_id)
            return 0

        # One message in the batch belongs to the user and cannot be removed for
        # everybody. Retry one by one so the bot's own messages still disappear.
        deleted = 0
        for cmid in cmids:
            try:
                await self._delete(api, peer_id, [cmid])
                deleted += 1
            except VKAPIError as error:
                if error.code == CANNOT_DELETE_FOR_ALL:
                    logger.debug(
                        "Message %s in peer %s cannot be deleted for everybody", cmid, peer_id
                    )
                else:
                    logger.warning(
                        "Could not delete message %s in peer %s: %s", cmid, peer_id, error
                    )
            except Exception:  # pragma: no cover - network failure must not break /add
                logger.exception("Unexpected error while deleting message %s", cmid)
        return deleted

    async def _delete(self, api: API, peer_id: int, cmids: list[int]) -> None:
        await api.messages.delete(
            peer_id=peer_id,
            cmids=cmids,
            delete_for_all=True,
            group_id=self._group_id,
        )
