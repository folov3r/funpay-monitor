from types import SimpleNamespace

import httpx
import pytest
from app.services.vk_upload import VkUploadError, upload_message_photo


class FakePhotos:
    def __init__(self, *, upload_url: str | None = "https://upload.example/photo") -> None:
        self.upload_url = upload_url
        self.saved: dict[str, object] = {}

    async def get_messages_upload_server(self, peer_id: int) -> SimpleNamespace:
        self.saved["peer_id"] = peer_id
        return SimpleNamespace(upload_url=self.upload_url)

    async def save_messages_photo(
        self,
        photo: str,
        hash: str | None = None,
        server: int | None = None,
    ) -> list[SimpleNamespace]:
        self.saved.update(photo=photo, hash=hash, server=server)
        return [SimpleNamespace(owner_id=-123, id=456)]


class FakeApi:
    def __init__(self, photos: FakePhotos) -> None:
        self.photos = photos


async def test_upload_message_photo_returns_attachment() -> None:
    photos = FakePhotos()
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(
            200,
            json={"photo": "{}", "hash": "secret", "server": 321},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        attachment = await upload_message_photo(
            FakeApi(photos),
            peer_id=42,
            image=b"\x89PNG\r\n\x1a\nfake",
            client=client,
        )

    assert attachment == "photo-123_456"
    assert seen["url"] == "https://upload.example/photo"
    assert str(seen["content_type"]).startswith("multipart/form-data")
    assert photos.saved == {
        "peer_id": 42,
        "photo": "{}",
        "hash": "secret",
        "server": 321,
    }


async def test_upload_message_photo_requires_upload_url() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(VkUploadError, match="upload URL"):
            await upload_message_photo(
                FakeApi(FakePhotos(upload_url=None)),
                peer_id=42,
                image=b"png",
                client=client,
            )


async def test_upload_message_photo_rejects_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"photo": ""})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(VkUploadError, match="photo/server"):
            await upload_message_photo(
                FakeApi(FakePhotos()),
                peer_id=42,
                image=b"png",
                client=client,
            )
