import aiohttp
import asyncio
import contextvars
import time
import logging
import random
from typing import Optional
from aiohttp import ClientTimeout
from yarl import URL

from core.config import ConfigManager, HOSTNAME_MIRRORS

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


class NetworkKernel:
    """Handles network operations with per-purpose proxy routing."""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self._last_req = 0.0
        self._rate_limit_lock: Optional[asyncio.Lock] = None
        # Metadata jobs can run concurrently. Keep failures task-local so one job
        # never renders another job's error message.
        self._fetch_error: contextvars.ContextVar[Optional[str]] = (
            contextvars.ContextVar("arsm_fetch_error", default=None)
        )
        self._mirror_health: dict[str, dict[str, float]] = {}

    @property
    def last_fetch_error(self) -> Optional[str]:
        """Return the current task's most recent metadata fetch failure."""
        return self._fetch_error.get()

    async def boot(self) -> None:
        """Initialize HTTP session."""
        if self.session is None or self.session.closed:
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Referer": "https://asmr.one/",
                "Origin": "https://asmr.one"
            }
            if self.config.auth_token:
                headers["Authorization"] = f"Bearer {self.config.auth_token}"

            timeout = ClientTimeout(
                total=None,
                connect=self.config.timeout,
                sock_read=self.config.timeout
            )

            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=timeout,
            )

    async def shutdown(self) -> None:
        """Close HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()

    def _ordered_mirrors(self) -> list[str]:
        configured = (self.config.mirror or "").rstrip("/")
        result = []
        for mirror in [configured, *HOSTNAME_MIRRORS]:
            value = (mirror or "").rstrip("/")
            if value and value not in result:
                result.append(value)
        order = {mirror: index for index, mirror in enumerate(result)}
        now = time.monotonic()
        return sorted(
            result,
            key=lambda mirror: (
                self._mirror_health.get(mirror, {}).get("cooldown_until", 0.0) > now,
                self._mirror_health.get(mirror, {}).get("failures", 0.0),
                self._mirror_health.get(mirror, {}).get("latency_ms", float("inf")),
                order[mirror],
            ),
        )

    def _record_mirror_success(self, mirror: str, elapsed: float) -> None:
        previous = self._mirror_health.get(mirror, {})
        old_latency = previous.get("latency_ms")
        latency_ms = max(0.0, elapsed * 1000.0)
        if old_latency is not None:
            latency_ms = old_latency * 0.7 + latency_ms * 0.3
        self._mirror_health[mirror] = {
            "failures": max(0.0, previous.get("failures", 0.0) - 1.0),
            "latency_ms": latency_ms,
            "cooldown_until": 0.0,
            "last_success": time.time(),
            "last_failure": previous.get("last_failure", 0.0),
        }

    def _record_mirror_failure(self, mirror: str,
                               retry_after: float | None = None) -> None:
        previous = self._mirror_health.get(mirror, {})
        failures = previous.get("failures", 0.0) + 1.0
        cooldown = max(float(retry_after or 0.0), min(60.0, 2.0 ** min(failures, 5.0)))
        self._mirror_health[mirror] = {
            **previous,
            "failures": failures,
            "cooldown_until": time.monotonic() + cooldown,
            "last_failure": time.time(),
        }

    def get_mirror_health(self) -> list[dict]:
        """Return a read-only runtime snapshot ordered by current preference."""
        now = time.monotonic()
        return [
            {
                "mirror": mirror,
                "failures": int(self._mirror_health.get(mirror, {}).get("failures", 0)),
                "latency_ms": self._mirror_health.get(mirror, {}).get("latency_ms"),
                "cooldown_seconds": max(
                    0.0,
                    self._mirror_health.get(mirror, {}).get("cooldown_until", 0.0) - now,
                ),
            }
            for mirror in self._ordered_mirrors()
        ]

    async def fetch(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Fetch JSON metadata with bounded mirror failover."""
        self._fetch_error.set(None)
        await self.boot()

        if self._rate_limit_lock is None:
            self._rate_limit_lock = asyncio.Lock()
        async with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_req
            if elapsed < 0.5:
                await asyncio.sleep(0.5 - elapsed)
            self._last_req = time.time()

        proxy = self.config.get_proxy_for('metadata')
        logger = logging.getLogger("echovault")
        last_error = None

        for mirror_index, mirror in enumerate(self._ordered_mirrors()):
            url = f"{mirror}{endpoint}"
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"FETCH metadata {url} proxy={proxy or 'direct'}")

            retry_after_seconds = None
            for attempt in range(2):
                started = time.monotonic()
                try:
                    async with self.session.get(
                        url, params=params, proxy=proxy
                    ) as resp:
                        if resp.status == 429:
                            last_error = RuntimeError(f"HTTP 429 from {mirror}")
                            try:
                                retry_after_seconds = float(
                                    resp.headers.get("Retry-After", "") or 0
                                )
                            except (TypeError, ValueError):
                                retry_after_seconds = None
                            await asyncio.sleep(
                                retry_after_seconds or 2 ** (attempt + 1)
                            )
                            continue
                        if resp.status == 404:
                            self._record_mirror_success(
                                mirror, time.monotonic() - started
                            )
                            self._fetch_error.set(f"HTTP 404 from {mirror}")
                            return None
                        resp.raise_for_status()
                        payload = await resp.json()
                        self._record_mirror_success(
                            mirror, time.monotonic() - started
                        )
                        if mirror_index > 0:
                            logger.info(
                                f"METADATA_MIRROR_RECOVERED mirror={mirror}")
                        self._fetch_error.set(None)
                        return payload
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                    last_error = exc
                    logger.warning(
                        f"Metadata request failed mirror={mirror} "
                        f"attempt={attempt+1}/2: {exc}")
                    if attempt == 0:
                        await asyncio.sleep(0.25)

            self._record_mirror_failure(mirror, retry_after_seconds)
            logger.warning(f"Switching metadata mirror after failure: {mirror}")

        logging.error(
            f"API request failed on all mirrors for {endpoint}: {last_error}")
        self._fetch_error.set(
            str(last_error) if last_error else "metadata request failed")
        return None

    async def stream(self, url: str, headers: dict = None,
                     purpose: str = 'download', *,
                     direct: bool = False) -> aiohttp.ClientResponse:
        """Stream a file with explicit per-purpose routing.

        ``direct=True`` is an exceptional, caller-audited bypass.  Normal cover
        requests never become audio/download requests just to evade a failed proxy.
        """
        await self.boot()
        proxy = None if direct else self.config.get_proxy_for(purpose)
        logging.getLogger("echovault").debug(
            "STREAM purpose=%s route=%s url=%s",
            purpose, "direct" if direct else (proxy or "direct"), url,
        )
        return await self.session.get(
            URL(url, encoded=True), headers=headers, proxy=proxy
        )
