from __future__ import annotations

from types import SimpleNamespace

from app.bot.cleanup import ChatCleaner
from vkbottle import VKAPIError


class FakeMessages:
    """Minimal stand-in for ``bot.api.messages`` recording delete calls.

    VK answers with one item per cmid and reports refusals as ``error`` on the
    item rather than raising, exactly like the real ``messages.delete``.
    """

    def __init__(self, refused: set[int] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._refused = refused or set()

    async def delete(
        self,
        *,
        peer_id: int,
        cmids: list[int],
        delete_for_all: bool,
        group_id: int | None = None,
    ) -> list[SimpleNamespace]:
        self.calls.append(
            {
                "peer_id": peer_id,
                "cmids": list(cmids),
                "delete_for_all": delete_for_all,
                "group_id": group_id,
            }
        )
        return [
            SimpleNamespace(
                conversation_message_id=cmid,
                error=SimpleNamespace(code=15, description="peer message")
                if cmid in self._refused
                else None,
            )
            for cmid in cmids
        ]


class RejectingMessages(FakeMessages):
    """Reject any multi-message batch with the whole-call VK error 924."""

    async def delete(
        self,
        *,
        peer_id: int,
        cmids: list[int],
        delete_for_all: bool,
        group_id: int | None = None,
    ) -> list[SimpleNamespace]:
        if len(cmids) > 1:
            self.calls.append(
                {
                    "peer_id": peer_id,
                    "cmids": list(cmids),
                    "delete_for_all": delete_for_all,
                    "group_id": group_id,
                }
            )
            raise VKAPIError[924](error_msg="Can't delete this message for everybody")
        return await super().delete(
            peer_id=peer_id,
            cmids=cmids,
            delete_for_all=delete_for_all,
            group_id=group_id,
        )


class FakeAPI:
    def __init__(self, messages: FakeMessages | None = None) -> None:
        self.messages = messages or FakeMessages()


def test_track_ignores_duplicates_and_none() -> None:
    cleaner = ChatCleaner()
    cleaner.track(1, [10, None, 10, 11])

    assert cleaner.tracked(1) == [10, 11]


def test_track_keeps_only_the_tail_of_a_long_dialog() -> None:
    cleaner = ChatCleaner(max_messages=3)
    cleaner.track(1, [1, 2, 3, 4, 5])

    assert cleaner.tracked(1) == [3, 4, 5]


def test_reset_and_forget_drop_the_chain() -> None:
    cleaner = ChatCleaner()
    cleaner.track(1, [1, 2])
    cleaner.reset(1)
    assert cleaner.tracked(1) == []

    cleaner.track(1, [3])
    cleaner.forget(1)
    assert cleaner.tracked(1) == []


async def test_purge_deletes_everything_except_kept_message() -> None:
    api = FakeAPI()
    cleaner = ChatCleaner(group_id=243253693)
    cleaner.track(528031218, [10, 11, 12])

    deleted = await cleaner.purge(api, 528031218, keep=[12])

    assert deleted == 2
    assert api.messages.calls == [
        {
            "peer_id": 528031218,
            "cmids": [10, 11],
            "delete_for_all": True,
            "group_id": 243253693,
        }
    ]
    assert cleaner.tracked(528031218) == []


async def test_purge_counts_only_messages_vk_actually_deleted() -> None:
    api = FakeAPI(FakeMessages(refused={11}))
    cleaner = ChatCleaner()
    cleaner.track(1, [10, 11, 12])

    deleted = await cleaner.purge(api, 1)

    assert deleted == 2
    assert [call["cmids"] for call in api.messages.calls] == [[10, 11, 12]]
    assert cleaner.tracked(1) == []


async def test_purge_retries_one_by_one_when_vk_rejects_the_batch() -> None:
    api = FakeAPI(RejectingMessages())
    cleaner = ChatCleaner()
    cleaner.track(1, [10, 11, 12])

    deleted = await cleaner.purge(api, 1)

    assert deleted == 3
    assert [call["cmids"] for call in api.messages.calls] == [[10, 11, 12], [10], [11], [12]]
    assert cleaner.tracked(1) == []


async def test_purge_is_noop_when_disabled() -> None:
    api = FakeAPI()
    cleaner = ChatCleaner(enabled=False)
    cleaner.track(1, [10])

    assert cleaner.tracked(1) == []
    assert await cleaner.purge(api, 1) == 0
    assert api.messages.calls == []


async def test_purge_of_empty_dialog_does_not_call_vk() -> None:
    api = FakeAPI()
    cleaner = ChatCleaner()

    assert await cleaner.purge(api, 1) == 0
    assert api.messages.calls == []
