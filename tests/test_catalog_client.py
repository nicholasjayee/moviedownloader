import json

from aiohttp import web

from moviebox_app.catalog.client import MovieboxClient


async def test_guest_bootstrap_token_refresh_and_search_transport(settings, monkeypatch):
    counts = {"home": 0, "search": 0}

    async def home(request):
        counts["home"] += 1
        return web.json_response(
            {"code": 0, "data": {}},
            headers={
                "x-user": json.dumps({"token": f"guest-{counts['home']}"}),
            },
        )

    async def search(request):
        counts["search"] += 1
        assert request.headers["Authorization"] == f"Bearer guest-{counts['home']}"
        assert (await request.json())["keyword"] == "Example"
        if counts["search"] == 1:
            return web.json_response({"code": 400, "message": "invalid token"})
        return web.json_response({"code": 0, "data": {"items": []}})

    upstream = web.Application()
    upstream.router.add_get("/home", home)
    upstream.router.add_post("/subject/search", search)
    runner = web.AppRunner(upstream)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    settings.catalog_api_base = f"http://127.0.0.1:{port}"

    def test_source_only(url):
        assert url.startswith(settings.catalog_api_base + "/")

    monkeypatch.setattr("moviebox_app.catalog.client.validate_url", test_source_only)
    client = MovieboxClient(settings)
    await client.open()
    try:
        assert await client.api("/subject/search", payload={"keyword": "Example"}) == {"items": []}
        assert counts == {"home": 2, "search": 2}
    finally:
        await client.close()
        await runner.cleanup()
