import asyncio

import pytest

from moviebox_app.downloads.manager import DownloadManager, JobConflict
from moviebox_app.downloads.transfer import Transfer, TransferError
from moviebox_app.models import DownloadRequest, Status
from moviebox_app.storage.paths import job_path
from moviebox_app.storage.repository import DownloadRepository


async def wait_finished(service, job_id):
    task = service.tasks.get(job_id)
    if task:
        await asyncio.wait_for(asyncio.shield(task), 2)
    return await service.get(job_id)


async def test_cancel_active_and_queued_jobs_then_retry(settings, monkeypatch):
    service = DownloadManager(settings, DownloadRepository(settings.database_path))
    started = asyncio.Event()
    release = asyncio.Event()

    async def transfer(self, job, checkpoint):
        partial = job_path(settings.download_dir, job.id, job.filename, partial=True)
        partial.write_bytes(b"partial")
        started.set()
        await release.wait()
        partial.replace(job_path(settings.download_dir, job.id, job.filename))
        job.downloaded_bytes = 7

    monkeypatch.setattr(Transfer, "run", transfer)
    await service.start()
    try:
        first = await service.add(DownloadRequest(url="https://example.org/one.mp4"))
        await asyncio.wait_for(started.wait(), 2)
        second = await service.add(DownloadRequest(url="https://example.org/two.mp4"))
        assert second.status == Status.QUEUED
        await service.cancel(second.id)
        await service.cancel(first.id)
        assert (await service.get(first.id)).status == Status.CANCELLED
        assert not list(settings.download_dir.glob("*.part"))
        release.set()
        await service.retry(first.id)
        assert (await wait_finished(service, first.id)).status == Status.COMPLETED
        with pytest.raises(JobConflict):
            await service.retry(first.id)
    finally:
        await service.close()


async def test_queue_bound_and_duplicate_prevention(settings, monkeypatch):
    async def transfer(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(Transfer, "run", transfer)
    service = DownloadManager(settings, DownloadRepository(settings.database_path))
    await service.start()
    try:
        request = DownloadRequest(url="https://example.org/one.mp4")
        await service.add(request)
        with pytest.raises(JobConflict, match="already"):
            await service.add(request)
        for index in range(2):
            await service.add(DownloadRequest(url=f"https://example.org/{index}.mp4"))
        with pytest.raises(JobConflict, match="full"):
            await service.add(DownloadRequest(url="https://example.org/overflow.mp4"))
    finally:
        await service.close()


async def test_failures_remove_partial_and_history_survives_restart(settings, monkeypatch):
    async def broken(self, job, checkpoint):
        job_path(settings.download_dir, job.id, job.filename, partial=True).write_bytes(b"bad")
        raise TransferError("Source closed early.")

    monkeypatch.setattr(Transfer, "run", broken)
    service = DownloadManager(settings, DownloadRepository(settings.database_path))
    await service.start()
    try:
        job = await service.add(DownloadRequest(url="https://example.org/one.mp4"))
        assert (await wait_finished(service, job.id)).status == Status.FAILED
        assert not list(settings.download_dir.glob("*.part"))
    finally:
        await service.close()
    reopened = DownloadManager(settings, DownloadRepository(settings.database_path))
    await reopened.start()
    try:
        assert (await reopened.get(job.id)).error == "Source closed early."
    finally:
        await reopened.close()


async def test_recovery_marks_interrupted_jobs_failed(settings):
    repository = DownloadRepository(settings.database_path)
    await repository.open()
    from moviebox_app.models import Download

    job = Download(
        id="a" * 32,
        url="https://example.org/a.mp4",
        title="A",
        filename="A.mp4",
        status=Status.DOWNLOADING,
        speed_bytes=100,
    )
    await repository.save(job)
    await repository.close()
    service = DownloadManager(settings, DownloadRepository(settings.database_path))
    await service.start()
    try:
        restored = await service.get(job.id)
        assert restored.status == Status.FAILED
        assert restored.speed_bytes == 0
        assert "Retry" in restored.error
    finally:
        await service.close()
