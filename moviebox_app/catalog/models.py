from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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


class Trailer(BaseModel):
    url: str
    poster: str = ""


class MediaDetails(BaseModel):
    movie: Movie
    seasons: list[Season] = Field(default_factory=list)
    description: str = ""
    country: str = ""
    release_date: str = ""
    cast: list[str] = Field(default_factory=list)
    trailer: Trailer | None = None


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
    episodes: list[Annotated[int, Field(strict=True, ge=1, le=10000)]] | None = Field(
        default=None, min_length=1, max_length=1000
    )

    @field_validator("episodes")
    @classmethod
    def unique_episodes(cls, value: list[int] | None) -> list[int] | None:
        return sorted(set(value)) if value is not None else None

    @model_validator(mode="after")
    def validate_selection(self):
        if self.episodes is not None and self.all_episodes:
            raise ValueError("Choose either specific episodes or the entire season.")
        if self.episodes and self.episode and self.episode not in self.episodes:
            raise ValueError("The preview episode must be one of the selected episodes.")
        return self
