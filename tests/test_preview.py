from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from moviebox_app.catalog.details import DetailsService
from moviebox_app.catalog.models import Movie
from moviebox_app.catalog.preview import trailer_from_subject


async def test_details_include_synopsis_cast_and_safe_trailer_and_cache_response():
    client = SimpleNamespace(
        api=AsyncMock(
            return_value={
                "subject": {
                    "title": "Preview movie",
                    "description": "A dragon story.",
                    "countryName": "Netherlands",
                    "releaseDate": "2010-09-27",
                    "genre": "Animation,Adventure",
                    "imdbRatingValue": "7.4",
                    "trailer": {
                        "videoAddress": {"url": "https://cdn.example.org/trailer.mp4"},
                        "cover": {"url": "https://cdn.example.org/poster.jpg"},
                    },
                },
                "stars": [
                    {"staffType": 1, "name": "Actor"},
                    {"staffType": 2, "name": "Director"},
                    {"staffType": 1, "name": " Actor "},
                ],
                "resource": {"seasons": [{"se": 0, "maxEp": 0}]},
            }
        )
    )
    lookup = AsyncMock(return_value=Movie(id="1", title="Old title", detail_path="preview-movie"))
    service = DetailsService(client, lookup)
    details = await service.get("1")
    assert details.movie.title == "Preview movie"
    assert details.movie.year == "2010"
    assert details.description == "A dragon story."
    assert details.country == "Netherlands"
    assert details.cast == ["Actor"]
    assert details.trailer.url == "https://cdn.example.org/trailer.mp4"
    assert details.seasons == []
    assert await service.get("1") == details
    client.api.assert_awaited_once()


@pytest.mark.parametrize(
    "trailer",
    [
        None,
        {},
        True,
        {"videoAddress": []},
        {"videoAddress": {"url": "javascript:alert(1)"}},
        {"videoAddress": {"url": "https://127.0.0.1/private.mp4"}},
        {"videoAddress": {"url": "https://user:secret@example.org/a.mp4"}},
        {"videoAddress": {"url": "https://[invalid"}},
    ],
)
def test_optional_or_unsafe_trailer_does_not_break_title_preview(trailer):
    assert trailer_from_subject({"trailer": trailer}) is None


async def test_missing_preview_metadata_keeps_existing_title_and_series_seasons():
    client = SimpleNamespace(
        api=AsyncMock(
            return_value={
                "resource": {"seasons": [{"se": 2, "maxEp": 7}]},
            }
        )
    )
    lookup = AsyncMock(return_value=Movie(id="2", title="Series", detail_path="series"))
    details = await DetailsService(client, lookup).get("2")
    assert details.movie.kind == "series"
    assert details.movie.title == "Series"
    assert details.description == ""
    assert details.trailer is None
    assert details.seasons[0].episodes == 7
