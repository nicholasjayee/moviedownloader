import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import aiofiles
import aiohttp

from moviebox_app.config import Settings
from moviebox_app.downloads.network import validate_url
from moviebox_app.downloads.resume import range_total
from moviebox_app.models import Download
from moviebox_app.storage.paths import VIDEO_EXTENSIONS, job_path


class TransferError(Exception):
    """An actionable error safe to show without leaking signed source URLs."""


class Transfer:
    def __init__(self, settings: Settings, session: aiohttp.ClientSession):
        self.settings = settings
        self.session = session

    async def run(self, job: Download, checkpoint: Callable[[], Awaitable[None]]) -> None:
        url = job.url
        partial = job_path(self.settings.download_dir, job.id, job.filename, partial=True)
        offset = 0
        if (job.etag or job.last_modified) and await asyncio.to_thread(partial.is_file):
            offset = (await asyncio.to_thread(partial.stat)).st_size
        for _ in range(6):
            validate_url(url)
            headers = dict(job.headers)
            if offset:
                headers.update(
                    {"Range": f"bytes={offset}-", "If-Range": job.etag or job.last_modified}
                )
            async with self.session.get(url, allow_redirects=False, headers=headers) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise TransferError("Source returned a redirect without a destination.")
                    url = urljoin(url, location)
                    continue
                if response.status == 416 and offset:
                    offset = 0
                    continue
                if response.status not in {200, 206}:
                    raise TransferError(f"Source returned HTTP {response.status}.")
                self.validate_response(response, url)
                if response.status == 206:
                    if not offset:
                        raise TransferError("Source returned an unexpected partial response.")
                    job.total_bytes = range_total(job, response, offset)
                    job.downloaded_bytes = offset
                else:
                    job.total_bytes = response.content_length
                    job.downloaded_bytes = 0
                if job.total_bytes and job.total_bytes > self.settings.max_file_bytes:
                    raise TransferError("This file exceeds the configured download size limit.")
                etag = response.headers.get("ETag", "")
                job.etag = etag if not etag.startswith("W/") else ""
                job.last_modified = response.headers.get("Last-Modified", "")
                await checkpoint()
                await self.write(job, response, checkpoint)
                return
        raise TransferError("Source redirected too many times.")

    def validate_response(self, response: aiohttp.ClientResponse, url: str) -> None:
        kind = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        generic = kind in {"", "application/octet-stream", "binary/octet-stream", "application/mp4"}
        known_suffix = Path(urlsplit(url).path).suffix.lower() in VIDEO_EXTENSIONS
        if not kind.startswith("video/") and not (generic and known_suffix):
            raise TransferError("This URL did not return a video file. Paste a direct media URL.")
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise TransferError("Source returned compressed content instead of a raw video file.")
        if response.content_length is not None:
            if response.content_length > self.settings.max_file_bytes:
                raise TransferError("This file exceeds the configured download size limit.")
            if response.content_length == 0:
                raise TransferError("Source returned an empty file.")

    async def write(self, job: Download, response, checkpoint) -> None:
        partial = job_path(self.settings.download_dir, job.id, job.filename, partial=True)
        final = job_path(self.settings.download_dir, job.id, job.filename)
        last_time = time.monotonic()
        last_bytes = job.downloaded_bytes
        async with aiofiles.open(partial, "ab" if job.downloaded_bytes else "wb") as output:
            async for chunk in response.content.iter_chunked(self.settings.chunk_size):
                if job.downloaded_bytes + len(chunk) > self.settings.max_file_bytes:
                    raise TransferError("This file exceeds the configured download size limit.")
                await output.write(chunk)
                job.downloaded_bytes += len(chunk)
                now = time.monotonic()
                if now - last_time >= 0.5:
                    job.speed_bytes = (job.downloaded_bytes - last_bytes) / (now - last_time)
                    last_time, last_bytes = now, job.downloaded_bytes
                    await checkpoint()
        if not job.downloaded_bytes:
            raise TransferError("Source returned an empty file.")
        if job.total_bytes is not None and job.downloaded_bytes != job.total_bytes:
            raise TransferError("Source closed before the complete file was received.")
        await asyncio.to_thread(partial.replace, final)
