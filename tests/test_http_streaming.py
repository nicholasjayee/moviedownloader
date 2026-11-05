"""A real loopback HTTP source checks transport integration without external media."""

import asyncio
import hashlib

import httpx
from aiohttp import web

from moviebox_app.app import create_app


async def test_http_stream_keeps_api_responsive_and_preserves_bytes(settings, monkeypatch):
    payload = bytes(range(256)) * 2048
    finished = asyncio.Event()

    async def source(request):
        response = web.StreamResponse(
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(len(payload)),
            }
        )
        await response.prepare(request)
        for offset in range(0, len(payload), 16384):
            await response.write(payload[offset : offset + 16384])
            await asyncio.sleep(0.01)
        await response.write_eof()
        finished.set()
        return response

    upstream = web.Application()
    upstream.router.add_get("/sample.mp4", source)
    runner = web.AppRunner(upstream)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    source_url = f"http://127.0.0.1:{port}/sample.mp4"

    # Only this exact test source bypasses the production public-network policy.
    def test_source_only(url):
        assert url == source_url

    monkeypatch.setattr("moviebox_app.downloads.manager.validate_url", test_source_only)
    monkeypatch.setattr("moviebox_app.downloads.transfer.validate_url", test_source_only)
    app = create_app(settings)
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                response = await client.post("/api/downloads", json={"url": source_url})
                assert response.status_code == 201
                job_id = response.json()["id"]
                await asyncio.sleep(0.05)
                health = await asyncio.wait_for(client.get("/api/health"), timeout=1)
                assert health.status_code == 200
                assert not finished.is_set()
                task = app.state.manager.tasks[job_id]
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
                job = (await client.get(f"/api/downloads/{job_id}")).json()
                assert job["status"] == "completed"
                assert job["downloaded_bytes"] == len(payload)
                saved = await client.get(f"/api/downloads/{job_id}/file")
                assert hashlib.sha256(saved.content).digest() == hashlib.sha256(payload).digest()
                ranged = await client.get(
                    f"/api/downloads/{job_id}/file", headers={"Range": "bytes=0-255"}
                )
                assert ranged.status_code == 206
                assert ranged.content == payload[:256]
    finally:
        await runner.cleanup()
