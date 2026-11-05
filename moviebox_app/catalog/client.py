"""Async Moviebox BFF client with a guest session and connection-time DNS checks."""

import asyncio
import json

import aiohttp

from moviebox_app.catalog.models import CatalogError
from moviebox_app.config import Settings
from moviebox_app.downloads.network import PublicResolver, validate_url

BROWSER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
)


class MovieboxClient:
    def __init__(self, settings: Settings):
        self.base = settings.catalog_api_base.rstrip("/")
        self.host = settings.catalog_host
        self.session: aiohttp.ClientSession | None = None
        self.resolver: PublicResolver | None = None
        self.token = ""
        self.token_lock = asyncio.Lock()

    async def open(self) -> None:
        self.resolver = PublicResolver()
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=8, resolver=self.resolver),
            timeout=aiohttp.ClientTimeout(total=25, connect=10),
            headers={"User-Agent": BROWSER_AGENT, "Accept": "application/json"},
            trust_env=False,
        )

    async def close(self) -> None:
        if self.session:
            await self.session.close()
        if self.resolver:
            await self.resolver.close()

    async def request(self, method: str, url: str, **kwargs) -> dict:
        assert self.session is not None
        try:
            validate_url(url)
            async with self.session.request(
                method, url, allow_redirects=False, **kwargs
            ) as response:
                if response.status != 200:
                    raise CatalogError(
                        f"Moviebox returned HTTP {response.status}. Try again shortly."
                    )
                if url.startswith(self.base + "/"):
                    try:
                        user = json.loads(response.headers.get("x-user", "{}"))
                        self.token = user.get("token") or self.token
                    except ValueError, AttributeError:
                        pass
                    if not self.token and "token" in response.cookies:
                        self.token = response.cookies["token"].value
                # Bound provider responses, including unexpected error documents.
                chunks = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    chunks.extend(chunk)
                    if len(chunks) > 4 * 1024 * 1024:
                        raise CatalogError("Moviebox returned an unexpectedly large response.")
                payload = json.loads(chunks)
                if not isinstance(payload, dict):
                    raise CatalogError("Moviebox returned an unexpected response.")
                return payload
        except aiohttp.ClientError, TimeoutError, OSError:
            raise CatalogError(
                "Could not connect to Moviebox. Check your connection and try again."
            ) from None
        except ValueError, UnicodeError:
            raise CatalogError(
                "Moviebox returned an unreadable response. Try again shortly."
            ) from None

    def api_headers(self) -> dict[str, str]:
        headers = {
            "Origin": f"https://{self.host}",
            "Referer": f"https://{self.host}/",
            "X-Request-Lang": "en",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def ensure_guest(self) -> None:
        async with self.token_lock:
            if not self.token:
                await self.request(
                    "GET",
                    self.base + "/home",
                    params={"host": self.host},
                    headers=self.api_headers(),
                )
                if not self.token:
                    raise CatalogError("Moviebox did not issue a guest session. Try again shortly.")

    async def api(
        self, path: str, *, payload: dict | None = None, params: dict | None = None
    ) -> dict | str:
        for attempt in range(2):
            await self.ensure_guest()
            data = await self.request(
                "POST" if payload is not None else "GET",
                self.base + path,
                params={"host": self.host, **(params or {})},
                headers=self.api_headers(),
                **({"json": payload} if payload is not None else {}),
            )
            if data.get("code") in {0, "0"}:
                return data.get("data") or {}
            if attempt == 0 and "token" in str(data.get("message", "")).lower():
                self.token = ""
                continue
            raise CatalogError("Moviebox could not complete this request. Try again shortly.")
        raise CatalogError("Moviebox guest session expired. Try again.")
