from typing import Literal

from pydantic import BaseModel, Field


class CatalogError(Exception):
    """Provider errors with messages safe to display to the user."""


class TitleNotFound(CatalogError):
    """The title has not been searched on this server yet."""


class Movie(BaseModel):
    id: str
    title: str
    detail_path: str
    year: str = ""
    rating: str = ""
    genres: str = ""
    poster: str = ""
    kind: Literal["movie", "series"] = "movie"


class Season(BaseModel):
    number: int
    episodes: int


class MediaDetails(BaseModel):
    movie: Movie
    seasons: list[Season] = Field(default_factory=list)


class SearchPage(BaseModel):
    movies: list[Movie]
    page: int
    has_more: bool = False


class Source(BaseModel):
    id: str
    quality: str
    size_bytes: int | None = None
    url: str
    headers: dict[str, str] = Field(default_factory=dict)

    def public(self) -> dict:
        return self.model_dump(exclude={"url", "headers"})


class MovieDownloadRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=80)
    season: int = Field(default=0, ge=0, le=1000)
    episode: int = Field(default=0, ge=0, le=10000)
    all_episodes: bool = False
