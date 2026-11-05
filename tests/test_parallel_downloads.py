"""Real HTTP streams verify overlapping transfers and automatic queue advancement."""

import asyncio

import httpx
from aiohttp import web

from moviebox_app.app import create_app


async def test_parallel_http_downloads_respect_limit_and_advance_queue(settings, monkeypatch):
    settings.concurrency = 2
    settings.max_queue = 3
    payload = b"first-chunk" * 2048 + b"last-chunk" * 2048
    started = asyncio.Queue()
    gates = {str(number): asyncio.Event() for number in range(3)}
    active = set()
    peak = 0

    async def source(request):
        nonlocal peak
        name = request.match_info["number"]
        active.add(name)
        peak = max(peak, len(active))
        response = web.StreamResponse(
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(len(payload)),
            }
        )
        try:
            await response.prepare(request)
            await response.write(payload[:1024])
            await started.put(name)
            await gates[name].wait()
            await response.write(payload[1024:])
            await response.write_eof()
            return response
        finally:
            active.remove(name)

    upstream = web.Application()
    upstream.router.add_get("/{number}.mp4", source)
    runner = web.AppRunner(upstream)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    urls = {f"http://127.0.0.1:{port}/{number}.mp4" for number in gates}

    def test_source_only(url):
        assert url in urls

    monkeypatch.setattr("moviebox_app.downloads.manager.validate_url", test_source_only)
    monkeypatch.setattr("moviebox_app.downloads.transfer.validate_url", test_source_only)
    app = create_app(settings)
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                jobs = []
                for url in sorted(urls):
                    response = await client.post("/api/downloads", json={"url": url})
                    assert response.status_code == 201
                    jobs.append(response.json())
                first = await asyncio.wait_for(started.get(), 3)
                second = await asyncio.wait_for(started.get(), 3)
                summary = (await client.get("/api/downloads")).json()["queue"]
                assert summary == {"downloading": 2, "queued": 1, "concurrency": 2}
                assert (await client.get("/api/health")).status_code == 200
                gates[first].set()
                third = await asyncio.wait_for(started.get(), 3)
                assert third not in {first, second}
                assert peak == 2
                gates[second].set()
                gates[third].set()
                await asyncio.wait_for(asyncio.gather(*list(app.state.manager.tasks.values())), 5)
                for job in jobs:
                    status = (await client.get(f"/api/downloads/{job['id']}")).json()
                    assert status["status"] == "completed"
                    assert (await client.get(f"/api/downloads/{job['id']}/file")).content == payload
    finally:
        for gate in gates.values():
            gate.set()
        await runner.cleanup()
