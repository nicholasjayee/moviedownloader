from collections.abc import Awaitable, Callable

from moviebox_app.catalog.cache import Cache
from moviebox_app.catalog.client import MovieboxClient
from moviebox_app.catalog.models import CatalogError, MediaDetails, Movie, Season


class DetailsService:
    def __init__(self, client: MovieboxClient, movie_lookup: Callable[[str], Awaitable[Movie]]):
        self.client = client
        self.movie_lookup = movie_lookup
        self.cache = Cache[MediaDetails](128, 300)

    async def get(self, movie_id: str) -> MediaDetails:
        cached = self.cache.get(movie_id)
        if cached:
            return cached
        movie = await self.movie_lookup(movie_id)
        data = await self.client.api("/detail", params={"detailPath": movie.detail_path})
        if not isinstance(data, dict):
            raise CatalogError("Moviebox returned unreadable title details.")
        seasons = []
        for entry in (data.get("resource") or {}).get("seasons") or []:
            try:
                number, episodes = int(entry.get("se", 0)), int(entry.get("maxEp", 0))
            except ValueError, TypeError:
                continue
            if number >= 0 and 0 < episodes <= 10000:
                seasons.append(Season(number=number, episodes=episodes))
        # Movie responses may include dummy seasons with zero episodes.
        kind = "series" if seasons else "movie"
        result = MediaDetails(movie=movie.model_copy(update={"kind": kind}), seasons=seasons)
        self.cache.put(movie_id, result)
        return result

    async def validate(self, movie_id: str, season: int, episode: int) -> MediaDetails:
        details = await self.get(movie_id)
        if details.movie.kind == "movie":
            if season or episode:
                raise ValueError("Movies use season 0 and episode 0.")
        elif not any(s.number == season and 1 <= episode <= s.episodes for s in details.seasons):
            raise ValueError("Choose a valid season and episode.")
        return details
