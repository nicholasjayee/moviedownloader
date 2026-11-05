import asyncio

import httpx
import pytest

from moviebox_app.app import create_app
from moviebox_app.catalog.models import CatalogError
from moviebox_app.catalog.repository import TitleRepository
from moviebox_app.catalog.service import CatalogService
from moviebox_app.downloads.transfer import Transfer
from moviebox_app.storage.paths import job_path


class Provider:
    def __init__(self):
        self.calls = []
        self.play_calls = 0

    async def api(self, path, *, payload=None, params=None):
        self.calls.append((path, payload, params))
        if path == "/subject/search":
            return {
                "items": [
                    {
                        "subjectId": "1",
                        "subjectType": 1,
                        "title": "Example movie",
                        "detailPath": "example-movie",
                        "releaseDate": "1968-01-01",
                    },
                    {
                        "subjectId": "2",
                        "subjectType": 2,
                        "title": "Example series",
                        "detailPath": "example-series",
                        "releaseDate": "2000-01-01",
                    },
                ],
                "pager": {"hasMore": True},
            }
        if path == "/detail":
            series = params["detailPath"] == "example-series"
            return {
                "resource": {"seasons": [{"se": 3 if series else 0, "maxEp": 3 if series else 0}]}
            }
        if path == "/media-player/get-domain":
            return "https://player.example.org/"
        if path == "/subject/caption":
            return {
                "captions": [
                    {
                        "lan": "en",
                        "lanName": "English",
                        "url": "https://cdn.example.org/subtitle.srt?secret=token",
                    }
                ]
            }
        raise AssertionError(path)

    async def request(self, method, url, **kwargs):
        self.play_calls += 1
        episode = kwargs["params"]["ep"]
        return {
            "code": 0,
            "data": {
                "streams": [
                    {
                        "id": f"video-{episode}",
                        "resolutions": "480",
                        "format": "MP4",
                        "size": "12",
                        "url": f"https://cdn.example.org/{episode}.mp4?secret={self.play_calls}",
                    },
                    {
                        "id": "locked",
                        "resolutions": "1080",
                        "format": "MP4",
                        "vipLocked": True,
                        "url": "https://cdn.example.org/locked.mp4",
                    },
                    {
                        "id": "hls",
                        "resolutions": "720",
                        "format": "HLS",
                        "url": "https://cdn.example.org/video.m3u8",
                    },
                ]
            },
        }


@pytest.fixture
async def catalog_app(settings):
    app = create_app(settings)
    provider = Provider()
    service = CatalogService(provider)
    async with app.router.lifespan_context(app):
        app.state.catalog = service
        app.state.manager.prepare = service.prepare_download
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            yield app, client, provider, service


async def test_search_details_quality_and_fresh_download_source(catalog_app, monkeypatch, settings):
    app, client, provider, service = catalog_app

    async def transfer(self, job, checkpoint):
        assert "secret=2" in job.url  # Source was refreshed at transfer time.
        assert job.headers["Referer"].startswith("https://player.example.org/")
        job_path(settings.download_dir, job.id, job.filename).write_bytes(b"sample video")
        job.downloaded_bytes = 12

    monkeypatch.setattr(Transfer, "run", transfer)
    response = await client.get("/api/movies/search", params={"q": "Example"})
    assert response.status_code == 200
    assert [movie["kind"] for movie in response.json()["movies"]] == ["movie", "series"]
    await client.get("/api/movies/search", params={"q": "Example"})
    assert sum(call[0] == "/subject/search" for call in provider.calls) == 1
    details = (await client.get("/api/movies/1/details")).json()
    assert details["seasons"] == []  # Dummy season zero does not make it a series.
    sources = await client.get("/api/movies/1/sources")
    assert sources.status_code == 200
    assert len(sources.json()["sources"]) == 1
    assert sources.json()["subtitles"][0]["name"] == "English"
    assert "secret" not in sources.text
    response = await client.post("/api/movies/1/download", json={"source_id": "video-0"})
    assert response.status_code == 201
    assert "secret" not in response.text
    job_id = response.json()["downloads"][0]["id"]
    task = app.state.manager.tasks.get(job_id)
    if task:
        await asyncio.wait_for(task, 2)
    assert (await client.get(f"/api/downloads/{job_id}")).json()["status"] == "completed"


async def test_series_episode_selection_and_atomic_season_queue(catalog_app, monkeypatch):
    app, client, provider, service = catalog_app

    async def transfer(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(Transfer, "run", transfer)
    await client.get("/api/movies/search", params={"q": "Example"})
    assert (await client.get("/api/movies/2/details")).json()["seasons"] == [
        {"number": 3, "episodes": 3}
    ]
    assert (await client.get("/api/movies/2/sources")).status_code == 400
    assert (await client.get("/api/movies/2/sources?season=3&episode=4")).status_code == 400
    sources = await client.get("/api/movies/2/sources?season=3&episode=1")
    assert sources.status_code == 200
    body = {"source_id": "video-1", "season": 3, "episode": 1, "all_episodes": True}
    response = await client.post("/api/movies/2/download", json=body)
    assert response.status_code == 201
    jobs = response.json()["downloads"]
    assert len(jobs) == 3
    assert "S03E02" in jobs[1]["title"]
    assert (await client.post("/api/movies/2/download", json=body)).status_code == 409
    assert len((await client.get("/api/downloads")).json()["downloads"]) == 3


async def test_provider_errors_and_expired_results_are_displayable(catalog_app, monkeypatch):
    app, client, provider, service = catalog_app
    assert (await client.get("/api/movies/missing/details")).status_code == 404
    assert (await client.get("/api/movies/search?q=%20%20")).status_code == 400

    async def unavailable(*args, **kwargs):
        raise CatalogError("Moviebox is unavailable. Try again.")

    monkeypatch.setattr(provider, "api", unavailable)
    response = await client.get("/api/movies/search?q=Example")
    assert response.status_code == 502
    assert "Try again" in response.json()["detail"]


async def test_subtitle_download_requires_a_listed_language(catalog_app, monkeypatch):
    app, client, provider, service = catalog_app
    await client.get("/api/movies/search?q=Example")

    async def subtitle(caption):
        return b"1\n00:00:00,000 --> 00:00:01,000\nExample\n"

    monkeypatch.setattr(service.subtitles, "fetch", subtitle)
    response = await client.get("/api/movies/1/subtitles/en")
    assert response.status_code == 200
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert b"Example" in response.content
    assert (await client.get("/api/movies/1/subtitles/missing")).status_code == 404


async def test_title_metadata_survives_reload_and_cache_expiry(settings):
    repository = TitleRepository(settings.database_path)
    await repository.open()
    try:
        first = CatalogService(Provider(), repository)
        await first.search("Example", 1)
    finally:
        await repository.close()
    reopened = TitleRepository(settings.database_path)
    await reopened.open()
    try:
        second = CatalogService(Provider(), reopened)
        details = await second.details_service.validate("2", 3, 2)
        assert details.movie.title == "Example series"
        sources = await second.sources("2", details.movie.detail_path, season=3, episode=2)
        assert sources[0].quality == "480p"
    finally:
        await reopened.close()
