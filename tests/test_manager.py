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


async def test_multiple_downloads_fill_slots_and_waiting_jobs_advance(settings, monkeypatch):
    settings.concurrency = 2
    settings.max_queue = 4
    service = DownloadManager(settings, DownloadRepository(settings.database_path))
    started = asyncio.Queue()
    gates = {}
    active = set()
    maximum = 0

    async def transfer(self, job, checkpoint):
        nonlocal maximum
        gate = gates.setdefault(job.id, asyncio.Event())
        active.add(job.id)
        maximum = max(maximum, len(active))
        await started.put(job.id)
        try:
            await gate.wait()
        finally:
            active.remove(job.id)

    monkeypatch.setattr(Transfer, "run", transfer)
    await service.start()
    try:
        jobs = await service.add_batch(
            [
                (DownloadRequest(url=f"https://example.org/{number}.mp4"), {}, {})
                for number in range(4)
            ]
        )
        first = await asyncio.wait_for(started.get(), 2)
        second = await asyncio.wait_for(started.get(), 2)
        assert service.summary() == {"downloading": 2, "queued": 2, "concurrency": 2}
        assert first != second
        first_task = service.tasks[first]
        gates[first].set()
        third = await asyncio.wait_for(started.get(), 2)
        assert third not in {first, second}
        await asyncio.wait_for(first_task, 2)
        assert maximum == 2
        gates[second].set()
        gates[third].set()
        fourth = await asyncio.wait_for(started.get(), 2)
        gates[fourth].set()
        await asyncio.wait_for(asyncio.gather(*list(service.tasks.values())), 2)
        completed = [await service.get(job.id) for job in jobs]
        assert all(job.status == Status.COMPLETED for job in completed)
        assert service.summary() == {"downloading": 0, "queued": 0, "concurrency": 2}
    finally:
        await service.close()


async def test_duplicate_entries_within_one_batch_are_rejected_before_saving(settings):
    service = DownloadManager(settings, DownloadRepository(settings.database_path))
    await service.start()
    try:
        entry = (DownloadRequest(url="https://example.org/one.mp4"), {}, {})
        with pytest.raises(JobConflict, match="already"):
            await service.add_batch([entry, entry])
        assert await service.list(200, 0) == []
        assert not service.tasks
    finally:
        await service.close()
