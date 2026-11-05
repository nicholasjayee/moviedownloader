from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from aiohttp import web
from starlette.requests import ClientDisconnect

from moviebox_app.app import create_app
from moviebox_app.catalog.models import CatalogError, MediaDetails, Movie, Source
from moviebox_app.downloads.network import validate_url
from moviebox_app.playback.ranges import validate_video_range
from moviebox_app.playback.response import VideoResponse


@pytest.fixture
async def streaming_app(settings, monkeypatch):
    payload = bytes(range(256)) * 100
    received = []

    async def video(request):
        received.append(dict(request.headers))
        assert request.headers["Referer"] == "https://player.example.org/"
        assert "Authorization" not in request.headers
        headers = {"Accept-Ranges": "bytes", "ETag": '"video-v1"'}
        ranged = request.headers.get("Range")
        if ranged:
            start, end = ranged.removeprefix("bytes=").split("-", 1)
            start = int(start) if start else max(0, len(payload) - int(end))
            end = (
                min(int(end), len(payload) - 1)
                if end and not ranged.startswith("bytes=-")
                else len(payload) - 1
            )
            if start >= len(payload):
                return web.Response(
                    status=416,
                    body=b"outside video",
                    headers={"Content-Range": f"bytes */{len(payload)}"},
                )
            headers["Content-Range"] = f"bytes {start}-{end}/{len(payload)}"
            return web.Response(
                status=206, body=payload[start : end + 1], headers=headers, content_type="video/mp4"
            )
        return web.Response(body=payload, headers=headers, content_type="video/mp4")

    async def html(request):
        return web.Response(text="<html>Not a video</html>", content_type="text/html")

    async def redirect(request):
        return web.Response(status=302, headers={"Location": "http://169.254.169.254/private.mp4"})

    upstream = web.Application()
    upstream.router.add_route("*", "/video.mp4", video)
    upstream.router.add_get("/html", html)
    upstream.router.add_get("/redirect", redirect)
    runner = web.AppRunner(upstream)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"

    def local_source_only(url):
        if url.startswith(base + "/"):
            return
        validate_url(url)

    monkeypatch.setattr("moviebox_app.playback.service.validate_url", local_source_only)
    state = SimpleNamespace(path="/video.mp4")

    async def validate(movie_id, season, episode):
        if (movie_id == "1" and (season or episode)) or (
            movie_id == "2" and (season != 2 or episode != 3)
        ):
            raise ValueError("Choose a valid episode.")
        return MediaDetails(movie=Movie(id=movie_id, title="Example", detail_path="example"))

    async def sources(*args, **kwargs):
        return [
            Source(
                id="video",
                quality="360p",
                url=base + state.path,
                headers={"Referer": "https://player.example.org/"},
            )
        ]

    app = create_app(settings)
    try:
        async with app.router.lifespan_context(app):
            app.state.catalog = SimpleNamespace(
                details_service=SimpleNamespace(validate=validate), sources=sources
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                yield client, payload, received, state
    finally:
        await runner.cleanup()


async def test_watch_supports_video_seeking_head_and_creates_no_downloads(streaming_app, settings):
    client, payload, received, state = streaming_app
    url = "/api/movies/1/watch?source_id=video"
    response = await client.get(
        url,
        headers={
            "Range": "bytes=4-255",
            "If-Range": '"video-v1"',
            "Authorization": "browser-secret",
        },
    )
    assert response.status_code == 206
    assert response.content == payload[4:256]
    assert response.headers["Content-Range"] == f"bytes 4-255/{len(payload)}"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert received[0]["If-Range"] == '"video-v1"'
    response = await client.head(url, headers={"Range": "bytes=0-9"})
    assert response.status_code == 206
    assert response.content == b""
    assert response.headers["Content-Length"] == "10"
    assert (await client.get(url)).content == payload
    assert (await client.get(url, headers={"Range": "bytes=-5"})).content == payload[-5:]
    assert (await client.get("/api/downloads")).json()["downloads"] == []
    assert list(settings.download_dir.iterdir()) == []


async def test_watch_reports_invalid_ranges_sources_and_episodes(streaming_app):
    client, payload, received, state = streaming_app
    assert (
        await client.get(
            "/api/movies/1/watch?source_id=video", headers={"Range": "bytes=0-9,20-29"}
        )
    ).status_code == 416
    assert received == []
    assert (await client.get("/api/movies/1/watch?source_id=missing")).status_code == 409
    assert (
        await client.get("/api/movies/2/watch?source_id=video&season=2&episode=2")
    ).status_code == 400
    assert (
        await client.get("/api/movies/2/watch?source_id=video&season=2&episode=3")
    ).status_code == 200
    response = await client.get(
        "/api/movies/1/watch?source_id=video", headers={"Range": "bytes=999999-"}
    )
    assert response.status_code == 416
    assert response.content == b""
    assert response.headers["Content-Range"] == f"bytes */{len(payload)}"


@pytest.mark.parametrize("path", ["/html", "/redirect"])
async def test_watch_rejects_non_video_and_private_redirects(streaming_app, path):
    client, payload, received, state = streaming_app
    state.path = path
    response = await client.get("/api/movies/1/watch?source_id=video")
    assert response.status_code == 502
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "requested, content_range, length",
    [
        ("bytes=0-9", "bytes 10-19/100", 10),
        ("bytes=0-9", "bytes 0-19/100", 20),
        ("bytes=0-9", "bytes 0-9/100", 9),
        ("bytes=0-", "bytes 0-100/100", 101),
        (None, "bytes 0-9/100", 10),
    ],
)
def test_invalid_upstream_ranges_cannot_be_forwarded_as_playable_video(
    requested, content_range, length
):
    with pytest.raises(CatalogError, match="invalid video range"):
        validate_video_range(requested, content_range, length)


async def test_disconnect_before_first_chunk_always_closes_upstream_video():
    async def chunks():
        yield b"video"

    upstream = MagicMock(status=200)
    upstream.content.iter_chunked.return_value = chunks()
    response = VideoResponse(upstream, 1024, {})

    async def disconnected(message):
        raise OSError("Browser closed the player")

    with pytest.raises(ClientDisconnect):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, None, disconnected)
    upstream.close.assert_called_once_with()
