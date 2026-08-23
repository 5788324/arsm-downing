"""Authenticated loopback bridge for the ARSM browser extension.

The extension never receives filesystem paths or direct database access.  It
can only query sanitized RJ states, enqueue one RJ through the existing
orchestrator, and ask the desktop UI to open a safe top-level view.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Mapping, Optional

from aiohttp import web

logger = logging.getLogger(__name__)

BROWSER_BRIDGE_HOST = "127.0.0.1"
BROWSER_BRIDGE_PORT = 17641
BROWSER_EXTENSION_ID = "mlncnjadnklkihapfcfcmaoookjlclba"
BROWSER_EXTENSION_ORIGIN = f"chrome-extension://{BROWSER_EXTENSION_ID}"
BROWSER_EXTENSION_OPAQUE_ORIGIN = "null"
MAX_REQUEST_BYTES = 16 * 1024
MAX_BATCH_RJ_IDS = 200
RATE_LIMIT_REQUESTS = 120
RATE_LIMIT_WINDOW_SECONDS = 60.0
_RJ_PATTERN = re.compile(r"^(?:RJ)?(\d{6,8})$", re.IGNORECASE)

QueueDownload = Callable[[str], Awaitable[Mapping[str, object]]]
OpenView = Callable[[str, str], None]


@dataclass(frozen=True)
class BrowserBridgeSnapshot:
    enabled: bool
    running: bool
    host: str
    port: int
    extension_id: str
    last_error: str = ""

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}"


def normalize_browser_rj_id(raw: object) -> str:
    """Return the canonical eight-digit RJ id or raise a safe validation error."""
    value = str(raw or "").strip()
    match = _RJ_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("RJ 号格式不正确")
    return f"RJ{int(match.group(1)):08d}"


def _row_value(row: object, key: str, default: object = "") -> object:
    try:
        if isinstance(row, Mapping):
            return row.get(key, default)
        return row[key]  # type: ignore[index]
    except (KeyError, TypeError, IndexError):
        return default


def _state_payload(
    canonical: str, *, in_library: bool, statuses: Iterable[object]
) -> dict[str, object]:
    normalized = {str(value or "").strip().lower() for value in statuses if value}
    if in_library:
        state = "in_library"
    elif normalized & {"downloading", "resuming"}:
        state = "downloading"
    elif normalized & {"queued", "prepared", "preparing"}:
        state = "queued"
    elif "paused" in normalized:
        state = "paused"
    elif normalized & {"failed", "metadata_failed", "partial"}:
        state = "failed"
    elif "cancelled" in normalized:
        state = "cancelled"
    elif normalized & {"completed", "registered", "verified", "indexed"}:
        state = "completed"
    else:
        state = "not_in_library"
    return {
        "rj_id": canonical,
        "state": state,
        "can_download": state == "not_in_library",
        "can_open": state != "not_in_library",
    }


def sanitized_rj_state(db, rj_id: str) -> dict[str, object]:
    """Build a path-free state snapshot from the existing database read model."""
    canonical = normalize_browser_rj_id(rj_id)
    statuses = [
        _row_value(row, "status", "") for row in (db.get_downloads_by_rj(canonical) or [])
    ]
    statuses.append(db.get_works_status(canonical) or "")
    return _state_payload(
        canonical,
        in_library=bool(db.find_in_library(canonical)),
        statuses=statuses,
    )


def sanitized_rj_states(db, rj_ids: Iterable[str]) -> dict[str, dict[str, object]]:
    """Build many states in one database batch when the vault supports it."""
    canonical = tuple(dict.fromkeys(normalize_browser_rj_id(value) for value in rj_ids))
    batch_reader = getattr(db, "get_rj_state_batch", None)
    if not callable(batch_reader):
        return {rj_id: sanitized_rj_state(db, rj_id) for rj_id in canonical}

    rows = batch_reader(canonical)
    result: dict[str, dict[str, object]] = {}
    for rj_id in canonical:
        row = rows.get(rj_id, {})
        result[rj_id] = _state_payload(
            rj_id,
            in_library=bool(row.get("in_library", False)),
            statuses=row.get("statuses", ()),
        )
    return result


class BrowserBridge:
    """Small aiohttp service bound only to the local loopback interface."""

    def __init__(
        self,
        db,
        queue_download: QueueDownload,
        open_view: OpenView,
        *,
        token: str,
        enabled: bool = False,
        host: str = BROWSER_BRIDGE_HOST,
        port: int = BROWSER_BRIDGE_PORT,
        allowed_extension_ids: Iterable[str] = (BROWSER_EXTENSION_ID,),
        rate_limit: int = RATE_LIMIT_REQUESTS,
    ) -> None:
        self.db = db
        self.queue_download = queue_download
        self.open_view = open_view
        self.token = str(token or "")
        self.enabled = bool(enabled)
        self.host = host
        self.port = int(port)
        self.allowed_extension_ids = frozenset(
            str(value).strip() for value in allowed_extension_ids if str(value).strip()
        )
        self.allowed_origins = frozenset(
            f"chrome-extension://{value}" for value in self.allowed_extension_ids
        )
        self.cors_origins = self.allowed_origins | {BROWSER_EXTENSION_OPAQUE_ORIGIN}
        self.rate_limit = max(1, int(rate_limit))
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._running = False
        self._bound_port = self.port
        self._last_error = ""

    @property
    def running(self) -> bool:
        return self._running

    @property
    def bound_port(self) -> int:
        return self._bound_port

    def snapshot(self) -> BrowserBridgeSnapshot:
        return BrowserBridgeSnapshot(
            enabled=self.enabled,
            running=self.running,
            host=self.host,
            port=self.bound_port,
            extension_id=BROWSER_EXTENSION_ID,
            last_error=self._last_error,
        )

    def configure(self, *, enabled: bool, token: str, port: int) -> None:
        self.enabled = bool(enabled)
        self.token = str(token or "")
        self.port = int(port)
        self._bound_port = self.port

    async def start(self) -> BrowserBridgeSnapshot:
        if self._running:
            return self.snapshot()
        if not self.enabled:
            return self.snapshot()
        if len(self.token) < 32:
            self._last_error = "浏览器扩展令牌无效"
            raise RuntimeError(self._last_error)
        if self.host != BROWSER_BRIDGE_HOST:
            self._last_error = "浏览器桥接只允许监听 127.0.0.1"
            raise RuntimeError(self._last_error)

        app = web.Application(client_max_size=MAX_REQUEST_BYTES)
        app.router.add_route("OPTIONS", "/{tail:.*}", self._handle_options)
        app.router.add_get("/v1/health", self._handle_health)
        app.router.add_post("/v1/library/status", self._handle_library_status)
        app.router.add_get("/v1/downloads/{rj_id}", self._handle_download_status)
        app.router.add_post("/v1/downloads", self._handle_enqueue)
        app.router.add_post("/v1/open", self._handle_open)

        self._runner = web.AppRunner(
            app,
            access_log=None,
            handle_signals=False,
        )
        await self._runner.setup()
        try:
            self._site = web.TCPSite(self._runner, self.host, self.port)
            await self._site.start()
            server = getattr(self._site, "_server", None)
            sockets = list(getattr(server, "sockets", ()) or ())
            if sockets:
                self._bound_port = int(sockets[0].getsockname()[1])
            self._running = True
            self._last_error = ""
            logger.info(
                "Browser bridge listening on %s:%s for extension %s",
                self.host,
                self._bound_port,
                BROWSER_EXTENSION_ID,
            )
            return self.snapshot()
        except Exception as exc:
            self._last_error = str(exc)
            await self.stop()
            raise

    async def stop(self) -> None:
        self._running = False
        site, runner = self._site, self._runner
        self._site = None
        self._runner = None
        if site is not None:
            await site.stop()
        if runner is not None:
            await runner.cleanup()
        self._requests.clear()

    def _cors_headers(self, origin: str) -> dict[str, str]:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers":
                "Content-Type, X-ARSM-Token, X-ARSM-Extension-Id",
            "Access-Control-Max-Age": "600",
            "Cache-Control": "no-store",
            "Vary": "Origin",
            "X-Content-Type-Options": "nosniff",
        }

    def _json(
        self,
        request: web.Request,
        payload: Mapping[str, object],
        *,
        status: int = 200,
    ) -> web.Response:
        origin = request.headers.get("Origin", "")
        return web.json_response(
            dict(payload),
            status=status,
            headers=self._cors_headers(origin) if origin in self.cors_origins else {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    def _error(
        self,
        request: web.Request,
        status: int,
        code: str,
        message: str,
    ) -> web.Response:
        return self._json(
            request,
            {"ok": False, "error": {"code": code, "message": message}},
            status=status,
        )

    def _client_key(self, request: web.Request) -> str:
        return "|".join((
            request.remote or "",
            request.headers.get("Origin", ""),
            request.headers.get("X-ARSM-Extension-Id", ""),
        ))

    def _consume_rate_limit(self, request: web.Request) -> bool:
        now = time.monotonic()
        window = self._requests[self._client_key(request)]
        while window and now - window[0] >= RATE_LIMIT_WINDOW_SECONDS:
            window.popleft()
        if len(window) >= self.rate_limit:
            return False
        window.append(now)
        return True

    def _authorize(self, request: web.Request) -> Optional[web.Response]:
        if request.remote not in {"127.0.0.1", "::1"}:
            return self._error(request, 403, "loopback_required", "只接受本机请求")

        origin = request.headers.get("Origin", "")
        extension_id = request.headers.get("X-ARSM-Extension-Id", "")
        if origin not in self.cors_origins:
            return self._error(request, 403, "origin_denied", "浏览器扩展来源未授权")
        if extension_id not in self.allowed_extension_ids:
            return self._error(request, 403, "extension_denied", "浏览器扩展 ID 未授权")
        if (
            origin != BROWSER_EXTENSION_OPAQUE_ORIGIN
            and origin != f"chrome-extension://{extension_id}"
        ):
            return self._error(request, 403, "origin_mismatch", "扩展来源与 ID 不匹配")

        supplied = request.headers.get("X-ARSM-Token", "")
        if not self.token or not hmac.compare_digest(supplied, self.token):
            return self._error(request, 401, "invalid_token", "连接令牌无效")
        if not self._consume_rate_limit(request):
            return self._error(request, 429, "rate_limited", "请求过于频繁，请稍后重试")
        return None

    async def _handle_options(self, request: web.Request) -> web.Response:
        origin = request.headers.get("Origin", "")
        extension_id = origin.removeprefix("chrome-extension://")
        if origin == BROWSER_EXTENSION_OPAQUE_ORIGIN:
            return web.Response(status=204, headers=self._cors_headers(origin))
        if origin not in self.allowed_origins or (
            extension_id not in self.allowed_extension_ids
        ):
            return self._error(request, 403, "origin_denied", "浏览器扩展来源未授权")
        return web.Response(status=204, headers=self._cors_headers(origin))

    async def _read_json(self, request: web.Request) -> Mapping[str, object]:
        try:
            payload = await request.json()
        except Exception as exc:
            raise ValueError("请求内容必须是 JSON") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("请求内容必须是 JSON 对象")
        return payload

    async def _handle_health(self, request: web.Request) -> web.Response:
        denied = self._authorize(request)
        if denied is not None:
            return denied
        return self._json(request, {
            "ok": True,
            "service": "ARSM Suite browser bridge",
            "protocol": 1,
            "extension_id": BROWSER_EXTENSION_ID,
        })

    async def _handle_library_status(self, request: web.Request) -> web.Response:
        denied = self._authorize(request)
        if denied is not None:
            return denied
        try:
            payload = await self._read_json(request)
            raw_values = payload.get("rj_ids", [])
            if not isinstance(raw_values, list):
                raise ValueError("rj_ids 必须是数组")
            if len(raw_values) > MAX_BATCH_RJ_IDS:
                raise ValueError(f"单次最多查询 {MAX_BATCH_RJ_IDS} 个 RJ")
            canonical = list(dict.fromkeys(
                normalize_browser_rj_id(value) for value in raw_values
            ))
        except ValueError as exc:
            return self._error(request, 400, "invalid_request", str(exc))

        states = sanitized_rj_states(self.db, canonical)
        return self._json(request, {"ok": True, "states": states})

    async def _handle_download_status(self, request: web.Request) -> web.Response:
        denied = self._authorize(request)
        if denied is not None:
            return denied
        try:
            state = sanitized_rj_state(self.db, request.match_info["rj_id"])
        except ValueError as exc:
            return self._error(request, 400, "invalid_rj_id", str(exc))
        return self._json(request, {"ok": True, "download": state})

    async def _handle_enqueue(self, request: web.Request) -> web.Response:
        denied = self._authorize(request)
        if denied is not None:
            return denied
        try:
            payload = await self._read_json(request)
            rj_id = normalize_browser_rj_id(payload.get("rj_id"))
        except ValueError as exc:
            return self._error(request, 400, "invalid_rj_id", str(exc))

        before = sanitized_rj_state(self.db, rj_id)
        if before["state"] == "in_library":
            return self._error(request, 409, "already_in_library", "作品已经在 ARSM 资源库中")
        if before["state"] in {"queued", "downloading"}:
            return self._error(request, 409, "already_queued", "作品已经在下载队列中")
        if before["state"] != "not_in_library":
            return self._error(
                request, 409, "requires_app", "请在 ARSM 中检查或恢复现有任务")

        try:
            result = dict(await self.queue_download(rj_id))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Browser bridge enqueue failed for %s", rj_id)
            return self._error(request, 500, "enqueue_failed", "ARSM 无法加入下载队列")

        core_status = str(result.get("status", "") or "")
        if core_status in {"already_queued", "already_running"}:
            return self._error(request, 409, core_status, "作品已经在下载队列中")
        if core_status != "queued":
            return self._json(request, {
                "ok": False,
                "download": {
                    "rj_id": rj_id,
                    "state": "failed",
                    "can_download": True,
                    "can_open": True,
                },
                "error": {
                    "code": core_status or "prepare_failed",
                    "message": "ARSM 准备下载失败，请在应用中查看原因",
                },
            }, status=502)

        return self._json(request, {
            "ok": True,
            "download": {
                "rj_id": rj_id,
                "state": "queued",
                "can_download": False,
                "can_open": True,
            },
        }, status=202)

    async def _handle_open(self, request: web.Request) -> web.Response:
        denied = self._authorize(request)
        if denied is not None:
            return denied
        try:
            payload = await self._read_json(request)
            rj_id = normalize_browser_rj_id(payload.get("rj_id"))
            view = str(payload.get("view", "download") or "download")
            if view not in {"download", "library"}:
                raise ValueError("view 只允许 download 或 library")
        except ValueError as exc:
            return self._error(request, 400, "invalid_request", str(exc))

        try:
            self.open_view(rj_id, view)
        except Exception:
            logger.exception("Browser bridge open request failed")
            return self._error(request, 500, "open_failed", "无法打开 ARSM 页面")
        return self._json(request, {"ok": True, "rj_id": rj_id, "view": view}, status=202)
