import json
from pathlib import Path

import aiosqlite

from moviebox_app.models import Download, Status


class DownloadRepository:
    def __init__(self, path: Path):
        self.path = path
        self.db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS downloads "
            "(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        await self.db.commit()

    async def close(self) -> None:
        if self.db:
            await self.db.close()

    async def save(self, job: Download) -> None:
        assert self.db is not None
        await self.db.execute(
            "INSERT INTO downloads VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (job.id, job.created_at, job.model_dump_json()),
        )
        await self.db.commit()

    async def get(self, job_id: str) -> Download | None:
        assert self.db is not None
        async with self.db.execute("SELECT payload FROM downloads WHERE id=?", (job_id,)) as cursor:
            row = await cursor.fetchone()
        return Download.model_validate_json(row[0]) if row else None

    async def list(self, limit: int = 200, offset: int = 0) -> list[Download]:
        assert self.db is not None
        async with self.db.execute(
            "SELECT payload FROM downloads ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Download.model_validate_json(row[0]) for row in rows]

    async def recover(self) -> None:
        """Interrupted jobs require explicit retry; never silently restart large transfers."""
        assert self.db is not None
        async with self.db.execute(
            "SELECT payload FROM downloads WHERE json_extract(payload, '$.status') IN (?, ?)",
            (Status.QUEUED, Status.DOWNLOADING),
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            data = json.loads(row[0])
            data.update(
                status=Status.FAILED, speed_bytes=0, error="App stopped. Retry to start again."
            )
            await self.save(Download.model_validate(data))
