import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

import aiohttp

from moviebox_app.config import Settings
from moviebox_app.downloads.identity import source_key
from moviebox_app.downloads.network import PublicResolver, validate_url
from moviebox_app.downloads.transfer import Transfer, TransferError
from moviebox_app.models import Download, DownloadRequest, Status
from moviebox_app.storage.paths import job_path, source_name
from moviebox_app.storage.repository import DownloadRepository

logger = logging.getLogger(__name__)


class JobConflict(Exception):
    pass


class DownloadManager:
    def __init__(
        self,
        settings: Settings,
        repository: DownloadRepository,
        prepare: Callable[[Download], Awaitable[None]] | None = None,
    ):
        self.settings = settings
        self.repository = repository
        self.prepare = prepare
        self.jobs: dict[str, Download] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.slots = asyncio.Semaphore(settings.concurrency)
        self.lock = asyncio.Lock()
        self.session: aiohttp.ClientSession | None = None
        self.resolver: PublicResolver | None = None

    async def start(self) -> None:
        self.settings.download_dir.mkdir(parents=True, exist_ok=True)
        await self.repository.open()
        await self.repository.recover()
        # Keep interrupted partials; Transfer validates their validators and ranges.
        self.resolver = PublicResolver()
        connector = aiohttp.TCPConnector(limit=self.settings.concurrency, resolver=self.resolver)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(
                total=None,
                connect=self.settings.connect_timeout,
                sock_read=self.settings.read_timeout,
            ),
            headers={"User-Agent": "Moviebox/0.1", "Accept-Encoding": "identity"},
            auto_decompress=False,
            trust_env=False,
        )

    async def close(self) -> None:
        for task in list(self.tasks.values()):
            task.cancel()
        await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)
        if self.session:
            await self.session.close()
        if self.resolver:
            await self.resolver.close()
        await self.repository.close()

    async def get(self, job_id: str) -> Download:
        job = self.jobs.get(job_id) or await self.repository.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    async def list(self, limit: int, offset: int) -> list[Download]:
        stored = await self.repository.list(limit, offset)
        return [self.jobs.get(job.id, job) for job in stored]

    def check_capacity(self) -> None:
        if len(self.tasks) >= self.settings.max_queue + self.settings.concurrency:
            raise JobConflict("Download queue is full. Wait for a download to finish.")

    def schedule(self, job: Download) -> None:
        self.jobs[job.id] = job
        self.tasks[job.id] = asyncio.create_task(self.run(job), name=f"download-{job.id}")

    def duplicate(self, url: str, provider: dict[str, str]) -> bool:
        key = source_key(url, provider)
        return any(source_key(job.url, job.provider) == key for job in self.jobs.values())

    def summary(self) -> dict[str, int]:
        return {
            "downloading": sum(job.status == Status.DOWNLOADING for job in self.jobs.values()),
            "queued": sum(job.status == Status.QUEUED for job in self.jobs.values()),
            "concurrency": self.settings.concurrency,
        }

    async def add(
        self,
        request: DownloadRequest,
        *,
        headers: dict[str, str] | None = None,
        provider: dict[str, str] | None = None,
    ) -> Download:
        return (await self.add_batch([(request, headers or {}, provider or {})]))[0]

    async def add_batch(self, entries: list[tuple[DownloadRequest, dict, dict]]) -> list[Download]:
        async with self.lock:
            if len(self.tasks) + len(entries) > self.settings.max_queue + self.settings.concurrency:
                raise JobConflict(
                    "Download queue is full. Wait for space before adding these downloads."
                )
            jobs = []
            seen = {source_key(job.url, job.provider) for job in self.jobs.values()}
            for request, headers, provider in entries:
                url = str(request.url)
                validate_url(url)
                key = source_key(url, provider)
                if key in seen:
                    raise JobConflict("This title or URL is already queued or downloading.")
                seen.add(key)
                title, filename = source_name(url, request.title)
                jobs.append(
                    Download(
                        id=uuid4().hex,
                        url=url,
                        title=title,
                        filename=filename,
                        headers=headers,
                        provider=provider,
                    )
                )
            for job in jobs:
                await self.repository.save(job)
            for job in jobs:
                self.schedule(job)
            return jobs

    async def cancel(self, job_id: str) -> Download:
        async with self.lock:
            job = await self.get(job_id)
            if job.status not in {Status.QUEUED, Status.DOWNLOADING}:
                raise JobConflict("Only queued or active downloads can be cancelled.")
            task = self.tasks.get(job_id)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            job.status, job.speed_bytes = Status.CANCELLED, 0
            await self.repository.save(job)
            self.tasks.pop(job_id, None)
            self.jobs.pop(job_id, None)
            return job

    async def retry(self, job_id: str) -> Download:
        async with self.lock:
            job = await self.get(job_id)
            if job.status not in {Status.FAILED, Status.CANCELLED}:
                raise JobConflict("Only failed or cancelled downloads can be retried.")
            # A visible failure can still be flushing its final checkpoint.
            previous = self.tasks.get(job_id)
            if previous:
                await asyncio.gather(previous, return_exceptions=True)
            self.check_capacity()
            if self.duplicate(job.url, job.provider):
                raise JobConflict("This URL is already queued or downloading.")
            job.status, job.error = Status.QUEUED, None
            job.speed_bytes = 0
            await self.repository.save(job)
            self.schedule(job)
            return job

    async def run(self, job: Download) -> None:
        try:
            async with self.slots:
                job.status = Status.DOWNLOADING
                if self.prepare and job.provider:
                    await self.prepare(job)
                await self.repository.save(job)
                assert self.session is not None
                await Transfer(self.settings, self.session).run(
                    job, lambda: self.repository.save(job)
                )
                job.status = Status.COMPLETED
        except asyncio.CancelledError:
            job.status = Status.CANCELLED
        except (TransferError, ValueError) as exc:
            job.status, job.error = Status.FAILED, str(exc)
        except aiohttp.ClientError, TimeoutError:
            job.status, job.error = (
                Status.FAILED,
                "Source connection failed or timed out. Try again.",
            )
        except OSError:
            job.status, job.error = (
                Status.FAILED,
                "Could not write the file. Check disk space and permissions.",
            )
        except Exception:
            # Do not log exception messages: network errors may include signed URLs.
            logger.error("Unexpected download failure for job %s", job.id)
            job.status, job.error = Status.FAILED, "Download failed unexpectedly. Try again."
        finally:
            job.speed_bytes = 0
            partial = job_path(self.settings.download_dir, job.id, job.filename, partial=True)
            try:
                if job.status == Status.COMPLETED or not (job.etag or job.last_modified):
                    await asyncio.to_thread(partial.unlink, missing_ok=True)
                if job.status != Status.COMPLETED:
                    final = job_path(self.settings.download_dir, job.id, job.filename)
                    await asyncio.to_thread(final.unlink, missing_ok=True)
                await self.repository.save(job)
            finally:
                self.tasks.pop(job.id, None)
                self.jobs.pop(job.id, None)
