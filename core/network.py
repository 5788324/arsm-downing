import aiohttp
import asyncio
import time
import logging
from typing import Optional
from core.config import ConfigManager
import random
from aiohttp import ClientTimeout

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

class NetworkKernel:
    """Handles network operations and API communication."""
    def __init__(self, config: ConfigManager):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self._last_req = 0
        self._rate_limit_lock = None

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
            
            connector = None
            # if getattr(self.config, 'dns', None):
            #     try:
            #         import aiohttp.resolver
            #         resolver = aiohttp.resolver.AsyncResolver(nameservers=[self.config.dns])
            #         connector = aiohttp.TCPConnector(resolver=resolver)
            #     except Exception:
            #         pass
                
            self.session = aiohttp.ClientSession(
                headers=headers, 
                timeout=timeout,
                connector=connector
            )

    async def shutdown(self) -> None:
        """Close HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Fetch JSON data from API endpoint."""
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
        proxy = self.config.proxy

        for attempt in range(3):
            try:
                async with self.session.get(url, params=params, proxy=proxy) as resp:
                    if resp.status == 429:  # Rate limit
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

    async def stream(self, url: str, headers: dict = None) -> aiohttp.ClientResponse:
        """Stream a file download."""
        await self.boot()
        proxy = self.config.proxy if self.config.proxy and getattr(self.config, 'proxy_download', False) else None
        return await self.session.get(url, headers=headers, proxy=proxy)
