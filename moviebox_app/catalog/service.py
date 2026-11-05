from urllib.parse import urlencode, urlsplit

from moviebox_app.catalog.cache import Cache
from moviebox_app.catalog.client import BROWSER_AGENT, MovieboxClient
from moviebox_app.catalog.details import DetailsService
from moviebox_app.catalog.models import CatalogError, Movie, SearchPage, Source, TitleNotFound
from moviebox_app.catalog.repository import TitleRepository
from moviebox_app.catalog.subtitles import SubtitleService
from moviebox_app.downloads.network import validate_url
from moviebox_app.downloads.transfer import TransferError
from moviebox_app.models import Download


class CatalogService:
    def __init__(self, client: MovieboxClient, repository: TitleRepository | None = None):
        self.client = client
        self.repository = repository
        self.searches = Cache[SearchPage](32, 60)
        self.movies = Cache[Movie](512, 1800)
        self.streams = Cache[list[Source]](128, 30)
        self.domains = Cache[str](1, 300)
        self.details_service = DetailsService(client, self.movie)
        self.subtitles = SubtitleService(client)

    async def search(self, query: str, page: int) -> SearchPage:
        query = query.strip()
        if not query:
            raise ValueError("Enter a movie title to search.")
        key = f"{page}:{query.casefold()}"
        cached = self.searches.get(key)
        if cached:
            # Keep metadata available even if another search displaced it.
            for movie in cached.movies:
                self.movies.put(movie.id, movie)
            return cached
        data = await self.client.api(
            "/subject/search",
            payload={
                "keyword": query,
                "page": page,
                "perPage": 12,
                "subjectType": 0,
            },
        )
        if not isinstance(data, dict):
            raise CatalogError("Moviebox returned an unexpected search response.")
        movies = []
        for item in data.get("items") or data.get("list") or []:
            if str(item.get("subjectType", 1)) not in {"1", "2"} or not item.get("subjectId"):
                continue
            movie = Movie(
                id=str(item["subjectId"]),
                title=item.get("title") or "Untitled movie",
                detail_path=item.get("detailPath") or "",
                year=str(item.get("releaseDate") or "")[:4],
                rating=str(item.get("imdbRatingValue") or ""),
                genres=item.get("genre") or "",
                poster=(item.get("cover") or {}).get("url") or "",
                kind="series" if str(item.get("subjectType")) == "2" else "movie",
            )
            if not movie.detail_path:
                continue
            self.movies.put(movie.id, movie)
            movies.append(movie)
        pager = data.get("pager") or {}
        result = SearchPage(movies=movies, page=page, has_more=bool(pager.get("hasMore")))
        if self.repository:
            await self.repository.save(movies)
        self.searches.put(key, result)
        return result

    async def movie(self, movie_id: str) -> Movie:
        movie = self.movies.get(movie_id)
        if movie is None and self.repository:
            movie = await self.repository.get(movie_id)
            if movie:
                self.movies.put(movie_id, movie)
        if movie is None:
            raise TitleNotFound("Search for this title again to load its details.")
        return movie

    async def sources(
        self,
        movie_id: str,
        detail_path: str,
        *,
        season: int = 0,
        episode: int = 0,
        fresh: bool = False,
    ) -> list[Source]:
        key = f"{movie_id}:{detail_path}:{season}:{episode}"
        cached = self.streams.get(key)
        if cached is not None and not fresh:
            return cached
        domain = self.domains.get("player")
        if domain is None:
            value = await self.client.api("/media-player/get-domain")
            if not isinstance(value, str) or urlsplit(value).path not in {"", "/"}:
                raise CatalogError("Moviebox returned an invalid player address.")
            validate_url(value)
            domain = value.rstrip("/")
            self.domains.put("player", domain)
        query = {"subjectId": movie_id, "detailPath": detail_path, "se": season, "ep": episode}
        referer = f"{domain}/spa/videoPlayPage/movies/{detail_path}?" + urlencode(
            {
                "id": movie_id,
                "type": "/movie/detail",
                "detailSe": season,
                "detailEp": episode,
                "lang": "en",
            }
        )
        data = await self.client.request(
            "GET",
            domain + "/wefeed-h5api-bff/subject/play",
            params=query,
            headers={"Referer": referer, "Origin": domain},
        )
        if data.get("code") not in {0, "0"}:
            raise CatalogError("Moviebox could not resolve this movie's video sources.")
        inner = data.get("data") or {}
        sources = []
        for stream in inner.get("streams") or []:
            if str(stream.get("format", "")).upper() != "MP4" or stream.get("vipLocked"):
                continue
            url = stream.get("url")
            if not url:
                continue
            try:
                validate_url(url)
                size = int(stream.get("size") or 0) or None
            except ValueError, TypeError:
                continue
            resolution = str(stream.get("resolutions") or "original")
            sources.append(
                Source(
                    id=str(stream.get("id") or resolution),
                    quality=f"{resolution}p" if resolution.isdigit() else resolution,
                    size_bytes=size,
                    url=url,
                    headers={"Referer": referer, "Origin": domain, "User-Agent": BROWSER_AGENT},
                )
            )
        sources.sort(
            key=lambda source: (
                int(source.quality.rstrip("p")) if source.quality.rstrip("p").isdigit() else 0
            ),
            reverse=True,
        )
        self.streams.put(key, sources)
        return sources

    async def prepare_download(self, job: Download) -> None:
        """Refresh expiring source links when a queued transfer actually gets a slot."""
        if not job.provider:
            return
        try:
            sources = await self.sources(
                job.provider["movie_id"],
                job.provider["detail_path"],
                season=int(job.provider.get("season", 0)),
                episode=int(job.provider.get("episode", 0)),
                fresh=True,
            )
            source = next(
                (item for item in sources if item.quality == job.provider["quality"]), None
            )
            if source is None:
                raise CatalogError(
                    "The selected quality is no longer available. Search and select it again."
                )
            job.url, job.headers = source.url, source.headers
        except CatalogError as exc:
            raise TransferError(str(exc)) from None
