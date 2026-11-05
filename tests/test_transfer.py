import asyncio
from contextlib import asynccontextmanager

import pytest

from moviebox_app.downloads.transfer import Transfer, TransferError
from moviebox_app.models import Download
from moviebox_app.storage.paths import job_path


class Content:
    def __init__(self, chunks):
        self.chunks = chunks

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            await asyncio.sleep(0)
            yield chunk


class Response:
    def __init__(self, chunks=(), *, kind="video/mp4", length=None, status=200, location=None):
        self.content = Content(chunks)
        self.content_length = length
        self.status = status
        self.headers = {"Content-Type": kind}
        if location:
            self.headers["Location"] = location


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.request_headers = []

    @asynccontextmanager
    async def get(self, url, **kwargs):
        self.calls.append(url)
        self.request_headers.append(kwargs.get("headers", {}))
        yield next(self.responses)


def make_job():
    return Download(
        id="a" * 32, url="https://example.org/movie.mp4", title="Movie", filename="Movie.mp4"
    )


async def checkpoint():
    pass


async def test_streams_and_renames_only_complete_file(settings):
    settings.download_dir.mkdir()
    job = make_job()
    session = Session([Response([b"first", b"second"], length=11)])
    await Transfer(settings, session).run(job, checkpoint)
    assert job.downloaded_bytes == 11
    assert job_path(settings.download_dir, job.id, job.filename).read_bytes() == b"firstsecond"
    assert not list(settings.download_dir.glob("*.part"))


async def test_redirect_to_private_address_is_never_requested(settings):
    session = Session([Response(status=302, location="http://127.0.0.1/private.mp4")])
    with pytest.raises(ValueError, match="private"):
        await Transfer(settings, session).run(make_job(), checkpoint)
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "response, message",
    [
        (Response([b"html"], kind="text/html"), "direct media"),
        (Response([b""], length=0), "empty"),
        (Response([b"short"], length=50), "complete file"),
        (Response([b"12345", b"67890"]), "size limit"),
        (Response(length=20), "size limit"),
        (Response(status=403), "HTTP 403"),
    ],
)
async def test_rejects_bad_responses_without_publishing_file(settings, response, message):
    settings.download_dir.mkdir()
    settings.max_file_bytes = 10
    job = make_job()
    if message == "complete file":
        settings.max_file_bytes = 100
    if message == "size limit" and response.content_length is None:
        settings.max_file_bytes = 8
    with pytest.raises(TransferError, match=message):
        await Transfer(settings, Session([response])).run(job, checkpoint)
    assert not job_path(settings.download_dir, job.id, job.filename).exists()


@pytest.mark.parametrize("ignores_range", [False, True])
async def test_resume_appends_only_for_matching_range_response(settings, ignores_range):
    settings.download_dir.mkdir()
    job = make_job()
    job.etag, job.total_bytes = '"version-one"', 11
    partial = job_path(settings.download_dir, job.id, job.filename, partial=True)
    partial.write_bytes(b"first")
    response = Response(
        [b"firstsecond"] if ignores_range else [b"second"],
        status=200 if ignores_range else 206,
        length=11 if ignores_range else 6,
    )
    response.headers["ETag"] = job.etag
    if not ignores_range:
        response.headers["Content-Range"] = "bytes 5-10/11"
    session = Session([response])
    await Transfer(settings, session).run(job, checkpoint)
    assert session.request_headers[0]["Range"] == "bytes=5-"
    assert session.request_headers[0]["If-Range"] == '"version-one"'
    assert job_path(settings.download_dir, job.id, job.filename).read_bytes() == b"firstsecond"


async def test_incorrect_range_is_never_appended(settings):
    settings.download_dir.mkdir()
    job = make_job()
    job.etag, job.total_bytes = '"version-one"', 11
    partial = job_path(settings.download_dir, job.id, job.filename, partial=True)
    partial.write_bytes(b"first")
    response = Response([b"second"], status=206, length=6)
    response.headers["Content-Range"] = "bytes 0-5/11"
    with pytest.raises(ValueError, match="invalid resume"):
        await Transfer(settings, Session([response])).run(job, checkpoint)
    assert partial.read_bytes() == b"first"
    assert job.etag == ""
