import aiohttp
import asyncio
import time
import logging
import random
from typing import Optional
from aiohttp import ClientTimeout

from core.config import ConfigManager

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

    async def fetch(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Fetch JSON data from API endpoint using metadata proxy."""
        await self.boot()

        # Rate limiting: 0.5s between requests
        if self._rate_limit_lock is None:
            self._rate_limit_lock = asyncio.Lock()
        async with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_req
            if elapsed < 0.5:
                await asyncio.sleep(0.5 - elapsed)
            self._last_req = time.time()

        url = f"{self.config.mirror}{endpoint}"
        proxy = self.config.get_proxy_for('metadata')

        for attempt in range(3):
            try:
                async with self.session.get(
                    url, params=params, proxy=proxy
                ) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(2 ** (attempt + 2))
                        continue
                    if resp.status == 404:
                        return None
                    resp.raise_for_status()
                    return await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == 2:
                    logging.error(f"API request failed: {e} for {url}")
                await asyncio.sleep(1)
        return None

    async def stream(self, url: str, headers: dict = None,
                     purpose: str = 'download') -> aiohttp.ClientResponse:
        """Stream a file download using the correct proxy for its purpose.

        Args:
            url: Download URL.
            headers: Extra HTTP headers (e.g. Range).
            purpose: 'download' or 'cover' — selects the right proxy.
        """
        await self.boot()
        proxy = self.config.get_proxy_for(purpose)
        return await self.session.get(url, headers=headers, proxy=proxy)
