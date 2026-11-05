import asyncio
import time

from fastapi.testclient import TestClient

from moviebox_app.app import create_app
from moviebox_app.downloads.transfer import Transfer
from moviebox_app.storage.paths import job_path


def test_ui_api_and_completed_file(settings, monkeypatch):
    async def transfer(self, job, checkpoint):
        await asyncio.sleep(0)
        job_path(settings.download_dir, job.id, job.filename).write_bytes(b"sample video")
        job.downloaded_bytes, job.total_bytes = 12, 12

    monkeypatch.setattr(Transfer, "run", transfer)
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert "Add a movie" in client.get("/").text
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/api/health").json() == {"status": "ok"}
        response = client.post(
            "/api/downloads", json={"url": "https://example.org/a.mp4?token=secret", "title": "A"}
        )
        assert response.status_code == 201
        assert "secret" not in response.text
        job_id = response.json()["id"]
        for _ in range(100):
            job = client.get(f"/api/downloads/{job_id}").json()
            if job["status"] == "completed":
                break
            time.sleep(0.01)
        assert job["status"] == "completed"
        assert client.get(f"/api/downloads/{job_id}/file").content == b"sample video"
        assert client.post(f"/api/downloads/{job_id}/cancel").status_code == 409
        assert client.get("/api/downloads/missing").status_code == 404
        assert len(client.get("/api/downloads").json()["downloads"]) == 1
        assert client.get("/api/downloads?limit=500").status_code == 422


def test_request_boundaries(settings):
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.post("/api/downloads", json={"url": "nope"}).status_code == 422
        assert (
            client.post("/api/downloads", json={"url": "http://127.0.0.1/a.mp4"}).status_code == 400
        )
        assert (
            client.post(
                "/api/downloads",
                headers={"Origin": "https://evil.example"},
                json={"url": "https://example.org/a.mp4"},
            ).status_code
            == 403
        )
        assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
        response = client.get("/")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
