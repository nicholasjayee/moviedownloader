"""Keep search metadata available across development reloads and app restarts."""

from pathlib import Path

import aiosqlite

from moviebox_app.catalog.models import Movie


class TitleRepository:
    def __init__(self, path: Path):
        self.path = path
        self.db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS catalog_titles (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        await self.db.commit()

    async def close(self) -> None:
        if self.db:
            await self.db.close()

    async def save(self, movies: list[Movie]) -> None:
        assert self.db is not None
        await self.db.executemany(
            "INSERT INTO catalog_titles VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            [(movie.id, movie.model_dump_json()) for movie in movies],
        )
        await self.db.commit()

    async def get(self, movie_id: str) -> Movie | None:
        assert self.db is not None
        async with self.db.execute(
            "SELECT payload FROM catalog_titles WHERE id=?", (movie_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return Movie.model_validate_json(row[0]) if row else None
