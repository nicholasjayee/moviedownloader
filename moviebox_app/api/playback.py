from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from moviebox_app.api.catalog import Catalog
from moviebox_app.playback.service import PlaybackService

router = APIRouter(prefix="/api/movies")


def playback(request: Request) -> PlaybackService:
    return request.app.state.playback


Playback = Annotated[PlaybackService, Depends(playback)]


@router.api_route("/{movie_id}/watch", methods=["GET", "HEAD"])
async def watch_movie(
    movie_id: str,
    request: Request,
    catalog: Catalog,
    player: Playback,
    source_id: str = Query(min_length=1, max_length=80),
    season: int = Query(0, ge=0, le=1000),
    episode: int = Query(0, ge=0, le=10000),
):
    details = await catalog.details_service.validate(movie_id, season, episode)
    sources = await catalog.sources(
        movie_id, details.movie.detail_path, season=season, episode=episode
    )
    source = next((item for item in sources if item.id == source_id), None)
    if source is None:
        raise HTTPException(409, "This video source expired. Reload the available qualities.")
    return await player.stream(
        source,
        request.headers.get("range"),
        request.headers.get("if-range"),
        head_only=request.method == "HEAD",
    )
