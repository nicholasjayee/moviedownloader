import re
from urllib.parse import urljoin

import aiohttp
from fastapi import HTTPException
from starlette.responses import Response

from moviebox_app.catalog.models import CatalogError, Source
from moviebox_app.config import Settings
from moviebox_app.downloads.network import PublicResolver, validate_url
from moviebox_app.playback.ranges import validate_video_range
from moviebox_app.playback.response import VideoResponse

FORWARDED_HEADERS = {
    "content-length",
    "content-range",
    "content-type",
    "accept-ranges",
    "etag",
    "last-modified",
}


class PlaybackService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session: aiohttp.ClientSession | None = None
        self.resolver: PublicResolver | None = None

    async def open(self) -> None:
        self.resolver = PublicResolver()
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=16, resolver=self.resolver),
            timeout=aiohttp.ClientTimeout(
                total=None,
                connect=self.settings.connect_timeout,
                sock_read=self.settings.read_timeout,
            ),
            auto_decompress=False,
            trust_env=False,
        )

    async def close(self) -> None:
        if self.session:
            await self.session.close()
        if self.resolver:
            await self.resolver.close()

    async def stream(
        self,
        source: Source,
        range_header: str | None = None,
        if_range: str | None = None,
        *,
        head_only: bool = False,
    ) -> Response:
        if range_header and (
            len(range_header) > 100 or not re.fullmatch(r"bytes=(?:\d+-\d*|-\d+)", range_header)
        ):
            raise HTTPException(416, "Only a single byte range is supported.")
        if if_range and (len(if_range) > 512 or "\r" in if_range or "\n" in if_range):
            raise HTTPException(400, "Invalid If-Range header.")
        assert self.session is not None
        headers = {**source.headers, "Accept-Encoding": "identity"}
        if range_header:
            headers["Range"] = range_header
        if if_range:
            headers["If-Range"] = if_range
        url = source.url
        upstream = None
        try:
            for _ in range(6):
                validate_url(url)
                upstream = await self.session.request(
                    "HEAD" if head_only else "GET", url, headers=headers, allow_redirects=False
                )
                if upstream.status in {301, 302, 303, 307, 308}:
                    location = upstream.headers.get("Location")
                    upstream.close()
                    if not location:
                        raise CatalogError("The video source returned an invalid redirect.")
                    url = urljoin(url, location)
                    continue
                break
            else:
                raise CatalogError("The video source redirected too many times.")
            forwarded = {
                key.lower(): value
                for key, value in upstream.headers.items()
                if key.lower() in FORWARDED_HEADERS
            }
            forwarded["Cache-Control"] = "private, no-store"
            if upstream.status == 416:
                upstream.close()
                return Response(
                    status_code=416,
                    headers={
                        key: value
                        for key, value in forwarded.items()
                        if key.lower() not in {"content-length", "content-type"}
                    },
                )
            if upstream.status not in {200, 206}:
                raise CatalogError(
                    f"The video source returned HTTP {upstream.status}. Try another quality."
                )
            kind = upstream.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if not kind.startswith("video/") and kind not in {
                "application/octet-stream",
                "application/mp4",
            }:
                raise CatalogError("The source did not return a playable video file.")
            if not kind.startswith("video/"):
                forwarded["content-type"] = "video/mp4"
            if upstream.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise CatalogError("The source returned compressed content instead of a video.")
            if upstream.status == 206:
                validate_video_range(
                    range_header, upstream.headers.get("Content-Range", ""), upstream.content_length
                )
            if head_only:
                upstream.close()
                return Response(status_code=upstream.status, headers=forwarded)
        except BaseException as exc:
            if upstream:
                upstream.close()
            if isinstance(exc, (aiohttp.ClientError, TimeoutError, OSError, ValueError)):
                raise CatalogError(
                    "Could not open the video source. Try again or choose another quality."
                ) from None
            raise

        return VideoResponse(upstream, self.settings.chunk_size, forwarded)
