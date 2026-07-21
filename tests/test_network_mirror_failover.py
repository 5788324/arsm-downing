import asyncio

import aiohttp

from core.config import ConfigManager
from core.network import NetworkKernel


class FailingContext:
    async def __aenter__(self):
        raise aiohttp.ClientConnectionError("offline")

    async def __aexit__(self, exc_type, exc, tb):
        return False


class JsonResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return self.payload


class FakeSession:
    closed = False

    def __init__(self):
        self.urls = []

    def get(self, url, params=None, proxy=None):
        self.urls.append(url)
        if url.startswith("https://primary.invalid"):
            return FailingContext()
        return JsonResponse({"ok": True, "url": url})

    async def close(self):
        self.closed = True


def test_configured_mirror_is_first_and_deduplicated() -> None:
    config = ConfigManager()
    config.mirror = "https://api.asmr.one/"
    kernel = NetworkKernel(config)
    mirrors = kernel._ordered_mirrors()
    assert mirrors[0] == "https://api.asmr.one"
    assert len(mirrors) == len(set(mirrors))


def test_fetch_fails_over_to_next_mirror(monkeypatch) -> None:
    config = ConfigManager()
    config.mirror = "https://primary.invalid"
    kernel = NetworkKernel(config)
    fake = FakeSession()
    kernel.session = fake

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    payload = asyncio.run(kernel.fetch("/api/workInfo/1"))

    assert payload["ok"] is True
    assert fake.urls[:2] == [
        "https://primary.invalid/api/workInfo/1",
        "https://primary.invalid/api/workInfo/1",
    ]
    assert fake.urls[2].startswith("https://api.asmr-200.com/")
