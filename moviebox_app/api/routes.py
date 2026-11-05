from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from moviebox_app.downloads.manager import DownloadManager, JobConflict
from moviebox_app.models import DownloadRequest, Status
from moviebox_app.storage.paths import job_path

router = APIRouter(prefix="/api")


def manager(request: Request) -> DownloadManager:
    return request.app.state.manager


Manager = Annotated[DownloadManager, Depends(manager)]


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/downloads")
async def list_downloads(
    service: Manager, limit: int = Query(200, ge=1, le=200), offset: int = Query(0, ge=0)
):
    jobs = await service.list(limit, offset)
    return {"downloads": [job.public() for job in jobs], "queue": service.summary()}


@router.post("/downloads", status_code=201)
async def create_download(body: DownloadRequest, service: Manager):
    return (await service.add(body)).public()


@router.get("/downloads/{job_id}")
async def get_download(job_id: str, service: Manager):
    return (await service.get(job_id)).public()


@router.post("/downloads/{job_id}/cancel")
async def cancel_download(job_id: str, service: Manager):
    return (await service.cancel(job_id)).public()


@router.post("/downloads/{job_id}/retry")
async def retry_download(job_id: str, service: Manager):
    return (await service.retry(job_id)).public()


@router.get("/downloads/{job_id}/file")
async def get_file(job_id: str, service: Manager):
    job = await service.get(job_id)
    if job.status != Status.COMPLETED:
        raise JobConflict("This download has not completed.")
    path = job_path(service.settings.download_dir, job.id, job.filename)
    if not path.is_file():
        raise KeyError(job_id)
    return FileResponse(path, filename=job.filename, media_type="application/octet-stream")
