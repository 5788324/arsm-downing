import asyncio
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest

from core.config import ConfigManager
from core.database import LibraryVault
from core.network import NetworkKernel
from core.orchestrator import Orchestrator


class UnauthorizedResponse:
    status = 401

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        raise aiohttp.ClientResponseError(
            request_info=SimpleNamespace(real_url="https://auth.invalid"),
            history=(),
            status=401,
            message="Unauthorized",
        )


class UnauthorizedSession:
    closed = False

    def get(self, *_args, **_kwargs):
        return UnauthorizedResponse()


class FailingMetadataKernel:
    last_fetch_error = "HTTP 401 Unauthorized"

    async def fetch(self, *_args, **_kwargs):
        return None

    async def shutdown(self):
        return None


def test_metadata_401_is_available_to_the_caller(monkeypatch) -> None:
    config = ConfigManager()
    config.mirror = "https://auth.invalid"
    kernel = NetworkKernel(config)
    kernel.session = UnauthorizedSession()
    monkeypatch.setattr(kernel, "_ordered_mirrors", lambda: [config.mirror])

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    async def run_request():
        assert await kernel.fetch("/api/workInfo/1") is None
        return kernel.last_fetch_error

    detail = asyncio.run(run_request())
    assert detail is not None
    assert "401" in detail


def test_prepare_surfaces_metadata_401(tmp_path: Path) -> None:
    config = ConfigManager()
    config.output_dir = tmp_path / "downloads"
    db = LibraryVault(tmp_path / "history.db")
    orchestrator = Orchestrator(FailingMetadataKernel(), config, db)

    async def run_request():
        with pytest.raises(RuntimeError, match="401"):
            await orchestrator._fetch_metadata_live("RJ00000001", "1")
        await orchestrator.shutdown()

    asyncio.run(run_request())
    db.close()