import asyncio
from dataclasses import dataclass

import aiohttp
import pytest

from core.browser_bridge import (
    BROWSER_EXTENSION_ID,
    BROWSER_EXTENSION_ORIGIN,
    BrowserBridge,
    normalize_browser_rj_id,
    sanitized_rj_states,
    sanitized_rj_state,
)
from core.database import LibraryVault


@dataclass
class _Row:
    status: str

    def __getitem__(self, key):
        if key == "status":
            return self.status
        raise KeyError(key)


class _FakeDb:
    def __init__(self):
        self.library = set()
        self.downloads = {}
        self.works = {}

    def find_in_library(self, rj_id):
        return [{"rj_id": rj_id}] if rj_id in self.library else []

    def get_downloads_by_rj(self, rj_id):
        return [_Row(value) for value in self.downloads.get(rj_id, [])]

    def get_works_status(self, rj_id):
        return self.works.get(rj_id, "")


def test_browser_rj_normalization_is_strict():
    assert normalize_browser_rj_id("RJ123456") == "RJ00123456"
    assert normalize_browser_rj_id("12345678") == "RJ12345678"

    for invalid in ("", "RJ12", "foo RJ12345678", "RJ123456789", "../RJ123456"):
        try:
            normalize_browser_rj_id(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid RJ: {invalid}")


def test_sanitized_state_never_exposes_paths():
    db = _FakeDb()
    db.library.add("RJ00000001")
    state = sanitized_rj_state(db, "RJ00000001")

    assert state == {
        "rj_id": "RJ00000001",
        "state": "in_library",
        "can_download": False,
        "can_open": True,
    }
    assert "path" not in repr(state).lower()


def test_sanitized_state_priority():
    db = _FakeDb()
    db.downloads["RJ00000001"] = ["paused", "downloading"]
    assert sanitized_rj_state(db, "RJ00000001")["state"] == "downloading"

    db.downloads["RJ00000001"] = ["failed"]
    assert sanitized_rj_state(db, "RJ00000001")["state"] == "failed"

    db.downloads["RJ00000001"] = []
    assert sanitized_rj_state(db, "RJ00000001")["state"] == "not_in_library"


def test_browser_bridge_end_to_end_loopback_contract():
    async def scenario():
        db = _FakeDb()
        db.library.add("RJ00000002")
        queued = []
        opened = []

        async def queue_download(rj_id):
            queued.append(rj_id)
            db.downloads[rj_id] = ["queued"]
            return {"status": "queued", "rj_id": rj_id}

        bridge = BrowserBridge(
            db,
            queue_download,
            lambda rj_id, view: opened.append((rj_id, view)),
            token="t" * 48,
            enabled=True,
            port=0,
        )
        await bridge.start()
        assert bridge.running is True
        endpoint = f"http://127.0.0.1:{bridge.bound_port}"
        headers = {
            "Origin": BROWSER_EXTENSION_ORIGIN,
            "X-ARSM-Extension-Id": BROWSER_EXTENSION_ID,
            "X-ARSM-Token": "t" * 48,
        }

        try:
            async with aiohttp.ClientSession() as session:
                response = await session.get(f"{endpoint}/v1/health", headers=headers)
                assert response.status == 200
                health = await response.json()
                assert health["ok"] is True
                assert health["extension_id"] == BROWSER_EXTENSION_ID
                assert "token" not in repr(health).lower()

                response = await session.options(
                    f"{endpoint}/v1/downloads",
                    headers={
                        "Origin": BROWSER_EXTENSION_ORIGIN,
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers":
                            "content-type,x-arsm-token,x-arsm-extension-id",
                    },
                )
                assert response.status == 204
                assert response.headers["Access-Control-Allow-Origin"] == (
                    BROWSER_EXTENSION_ORIGIN
                )

                response = await session.post(
                    f"{endpoint}/v1/library/status",
                    headers=headers,
                    json={"rj_ids": ["RJ00000001", "RJ00000002", "00000001"]},
                )
                assert response.status == 200
                states = (await response.json())["states"]
                assert list(states) == ["RJ00000001", "RJ00000002"]
                assert states["RJ00000001"]["state"] == "not_in_library"
                assert states["RJ00000002"]["state"] == "in_library"

                response = await session.post(
                    f"{endpoint}/v1/downloads",
                    headers=headers,
                    json={"rj_id": "RJ00000001"},
                )
                assert response.status == 202
                assert (await response.json())["download"]["state"] == "queued"
                assert queued == ["RJ00000001"]

                response = await session.post(
                    f"{endpoint}/v1/downloads",
                    headers=headers,
                    json={"rj_id": "RJ00000001"},
                )
                assert response.status == 409
                assert (await response.json())["error"]["code"] == "already_queued"

                response = await session.post(
                    f"{endpoint}/v1/downloads",
                    headers=headers,
                    json={"rj_id": "RJ00000002"},
                )
                assert response.status == 409
                assert (await response.json())["error"]["code"] == (
                    "already_in_library"
                )

                response = await session.post(
                    f"{endpoint}/v1/open",
                    headers=headers,
                    json={"rj_id": "RJ00000002", "view": "library"},
                )
                assert response.status == 202
                assert opened == [("RJ00000002", "library")]

                bad_headers = dict(headers)
                bad_headers["Origin"] = "https://asmr.one"
                response = await session.get(
                    f"{endpoint}/v1/health", headers=bad_headers
                )
                assert response.status == 403

                bad_headers = dict(headers)
                bad_headers["X-ARSM-Token"] = "wrong"
                response = await session.get(
                    f"{endpoint}/v1/health", headers=bad_headers
                )
                assert response.status == 401
        finally:
            await bridge.stop()

        assert bridge.running is False

    asyncio.run(scenario())


def test_browser_bridge_rate_limit():
    async def scenario():
        db = _FakeDb()

        async def queue_download(rj_id):
            return {"status": "queued", "rj_id": rj_id}

        bridge = BrowserBridge(
            db,
            queue_download,
            lambda _rj_id, _view: None,
            token="r" * 48,
            enabled=True,
            port=0,
            rate_limit=2,
        )
        await bridge.start()
        headers = {
            "Origin": BROWSER_EXTENSION_ORIGIN,
            "X-ARSM-Extension-Id": BROWSER_EXTENSION_ID,
            "X-ARSM-Token": "r" * 48,
        }
        endpoint = f"http://127.0.0.1:{bridge.bound_port}"
        try:
            async with aiohttp.ClientSession() as session:
                assert (await session.get(
                    f"{endpoint}/v1/health", headers=headers
                )).status == 200
                assert (await session.get(
                    f"{endpoint}/v1/health", headers=headers
                )).status == 200
                response = await session.get(
                    f"{endpoint}/v1/health", headers=headers
                )
                assert response.status == 429
        finally:
            await bridge.stop()

    asyncio.run(scenario())


def test_batch_state_reader_uses_three_selects_for_many_cards(tmp_path):
    db = LibraryVault(tmp_path / "browser-batch.db")
    try:
        db.upsert_library_entry("RJ00000002", str(tmp_path), str(tmp_path / "RJ00000002"))
        db.upsert_download(
            "track-1", "RJ00000003", "track.mp3", str(tmp_path / "track.mp3"), "downloading"
        )
        statements = []
        db.conn.set_trace_callback(statements.append)

        states = sanitized_rj_states(
            db, ["RJ00000001", "RJ00000002", "RJ00000003"]
        )

        selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
        assert len(selects) == 3
        assert states["RJ00000001"]["state"] == "not_in_library"
        assert states["RJ00000002"]["state"] == "in_library"
        assert states["RJ00000003"]["state"] == "downloading"
        assert "path" not in repr(states).lower()
    finally:
        db.close()


@pytest.mark.parametrize(
    ("downloads", "work_status", "expected"),
    [
        (["queued"], "", "queued"),
        (["downloading"], "", "downloading"),
        (["paused"], "", "paused"),
        (["failed"], "", "failed"),
        (["cancelled"], "", "cancelled"),
        (["completed"], "", "completed"),
        ([], "prepared", "queued"),
        ([], "partial", "failed"),
        ([], "", "not_in_library"),
    ],
)
def test_sanitized_state_matrix(downloads, work_status, expected):
    db = _FakeDb()
    db.downloads["RJ00000001"] = downloads
    if work_status:
        db.works["RJ00000001"] = work_status
    assert sanitized_rj_state(db, "RJ00000001")["state"] == expected


def test_multitab_fast_clicks_create_only_one_queue_entry():
    async def scenario():
        db = _FakeDb()
        core_lock = asyncio.Lock()
        queued = set()

        async def queue_download(rj_id):
            async with core_lock:
                await asyncio.sleep(0)
                if rj_id in queued:
                    return {"status": "already_queued", "rj_id": rj_id}
                queued.add(rj_id)
                db.downloads[rj_id] = ["queued"]
                return {"status": "queued", "rj_id": rj_id}

        bridge = BrowserBridge(
            db,
            queue_download,
            lambda _rj_id, _view: None,
            token="m" * 48,
            enabled=True,
            port=0,
        )
        await bridge.start()
        headers = {
            "Origin": BROWSER_EXTENSION_ORIGIN,
            "X-ARSM-Extension-Id": BROWSER_EXTENSION_ID,
            "X-ARSM-Token": "m" * 48,
        }
        endpoint = f"http://127.0.0.1:{bridge.bound_port}"
        try:
            async with aiohttp.ClientSession() as session:
                responses = await asyncio.gather(*(
                    session.post(
                        f"{endpoint}/v1/downloads",
                        headers=headers,
                        json={"rj_id": "RJ00000001"},
                    )
                    for _ in range(12)
                ))
                statuses = [response.status for response in responses]
                payloads = [await response.json() for response in responses]
                assert statuses.count(202) == 1
                assert statuses.count(409) == 11
                assert queued == {"RJ00000001"}
                assert all(
                    payload.get("ok") is True
                    or payload.get("error", {}).get("code") == "already_queued"
                    for payload in payloads
                )
        finally:
            await bridge.stop()

    asyncio.run(scenario())


def test_bridge_stop_restart_and_large_batch_recovery():
    async def scenario():
        db = _FakeDb()

        async def queue_download(rj_id):
            return {"status": "queued", "rj_id": rj_id}

        bridge = BrowserBridge(
            db,
            queue_download,
            lambda _rj_id, _view: None,
            token="s" * 48,
            enabled=True,
            port=0,
        )
        headers = {
            "Origin": BROWSER_EXTENSION_ORIGIN,
            "X-ARSM-Extension-Id": BROWSER_EXTENSION_ID,
            "X-ARSM-Token": "s" * 48,
        }
        await bridge.start()
        first_endpoint = f"http://127.0.0.1:{bridge.bound_port}"
        async with aiohttp.ClientSession() as session:
            assert (await session.get(
                f"{first_endpoint}/v1/health", headers=headers
            )).status == 200
        await bridge.stop()
        assert bridge.running is False

        await bridge.start()
        second_endpoint = f"http://127.0.0.1:{bridge.bound_port}"
        batch = [f"RJ{value:08d}" for value in range(1, 201)]
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.post(
                    f"{second_endpoint}/v1/library/status",
                    headers=headers,
                    json={"rj_ids": batch},
                )
                assert response.status == 200
                assert len((await response.json())["states"]) == 200

                response = await session.post(
                    f"{second_endpoint}/v1/library/status",
                    headers=headers,
                    json={"rj_ids": batch + ["RJ00000201"]},
                )
                assert response.status == 400
                assert (await response.json())["error"]["code"] == "invalid_request"
        finally:
            await bridge.stop()

    asyncio.run(scenario())
