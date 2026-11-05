import re
from urllib.parse import urljoin

import aiohttp
from pydantic import BaseModel

from moviebox_app.catalog.cache import Cache
from moviebox_app.catalog.client import MovieboxClient
from moviebox_app.catalog.models import CatalogError
from moviebox_app.downloads.network import validate_url


class Caption(BaseModel):
    language: str
    name: str
    url: str


class SubtitleService:
    def __init__(self, client: MovieboxClient):
        self.client = client
        self.cache = Cache[list[Caption]](128, 60)

    async def list(self, movie_id: str, detail_path: str, stream_id: str) -> list[Caption]:
        key = f"{movie_id}:{stream_id}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        data = await self.client.api(
            "/subject/caption",
            params={
                "format": "MP4",
                "id": stream_id,
                "subjectId": movie_id,
                "detailPath": detail_path,
            },
        )
        raw = data.get("captions", []) if isinstance(data, dict) else data
        captions = []
        for item in raw if isinstance(raw, list) else []:
            language = str(item.get("lan") or "")
            url = item.get("url") or ""
            if not re.fullmatch(r"[\w-]{1,20}", language):
                continue
            try:
                validate_url(url)
            except ValueError:
                continue
            captions.append(
                Caption(language=language, name=item.get("lanName") or language, url=url)
            )
        self.cache.put(key, captions)
        return captions

    async def fetch(self, caption: Caption) -> bytes:
        assert self.client.session is not None
        url = caption.url
        try:
            for _ in range(6):
                validate_url(url)
                async with self.client.session.get(url, allow_redirects=False) as response:
                    if response.status in {301, 302, 303, 307, 308} and response.headers.get(
                        "Location"
                    ):
                        url = urljoin(url, response.headers["Location"])
                        continue
                    if response.status != 200:
                        raise CatalogError("The subtitle file is currently unavailable.")
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        data.extend(chunk)
                        if len(data) > 5 * 1024 * 1024:
                            raise CatalogError("The subtitle file exceeds the size limit.")
                    kind = response.headers.get("Content-Type", "").lower()
                    if "text/html" in kind or not data:
                        raise CatalogError("The source did not return a subtitle file.")
                    return bytes(data)
        except aiohttp.ClientError, TimeoutError, OSError, ValueError:
            raise CatalogError("Could not download the subtitle file. Try again.") from None
        raise CatalogError("The subtitle source redirected too many times.")
