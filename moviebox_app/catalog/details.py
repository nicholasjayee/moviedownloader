from collections.abc import Awaitable, Callable

from moviebox_app.catalog.cache import Cache
from moviebox_app.catalog.client import MovieboxClient
from moviebox_app.catalog.models import CatalogError, MediaDetails, Movie, Season
from moviebox_app.catalog.preview import cast_names, public_media_url, trailer_from_subject


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
        subject = data.get("subject") or {}
        if not isinstance(subject, dict):
            subject = {}
        updates = {"kind": kind}
        for field, value in {
            "title": subject.get("title"),
            "year": str(subject.get("releaseDate") or "")[:4],
            "genres": subject.get("genre"),
            "rating": str(subject.get("imdbRatingValue") or ""),
            "poster": public_media_url((subject.get("cover") or {}).get("url"))
            if isinstance(subject.get("cover"), dict)
            else "",
        }.items():
            if isinstance(value, str) and value:
                updates[field] = value
        result = MediaDetails(
            movie=movie.model_copy(update=updates),
            seasons=seasons,
            description=subject.get("description")
            if isinstance(subject.get("description"), str)
            else "",
            country=subject.get("countryName")
            if isinstance(subject.get("countryName"), str)
            else "",
            release_date=str(subject.get("releaseDate") or ""),
            cast=cast_names(data.get("stars")),
            trailer=trailer_from_subject(subject),
        )
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
