from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from moviebox_app.api.routes import Manager
from moviebox_app.catalog.models import CatalogError, MovieDownloadRequest
from moviebox_app.catalog.selection import selected_episodes
from moviebox_app.catalog.service import CatalogService
from moviebox_app.models import DownloadRequest
from moviebox_app.storage.paths import source_name

router = APIRouter(prefix="/api/movies")


def catalog(request: Request) -> CatalogService:
    return request.app.state.catalog


Catalog = Annotated[CatalogService, Depends(catalog)]


@router.get("/search")
async def search_movies(
    service: Catalog,
    q: str = Query(min_length=1, max_length=160),
    page: int = Query(1, ge=1, le=100),
):
    return await service.search(q, page)


@router.get("/{movie_id}/sources")
async def movie_sources(
    movie_id: str,
    service: Catalog,
    season: int = Query(0, ge=0, le=1000),
    episode: int = Query(0, ge=0, le=10000),
):
    details = await service.details_service.validate(movie_id, season, episode)
    movie = details.movie
    sources = await service.sources(movie.id, movie.detail_path, season=season, episode=episode)
    captions = []
    subtitle_error = None
    if sources:
        try:
            captions = await service.subtitles.list(movie.id, movie.detail_path, sources[0].id)
        except CatalogError as exc:
            subtitle_error = str(exc)
    return {
        "movie": movie,
        "sources": [source.public() for source in sources],
        "subtitles": [caption.model_dump(exclude={"url"}) for caption in captions],
        "subtitle_error": subtitle_error,
    }


@router.get("/{movie_id}/subtitles/{language}")
async def download_subtitle(
    movie_id: str,
    language: str,
    service: Catalog,
    season: int = Query(0, ge=0, le=1000),
    episode: int = Query(0, ge=0, le=10000),
):
    details = await service.details_service.validate(movie_id, season, episode)
    movie = details.movie
    sources = await service.sources(movie.id, movie.detail_path, season=season, episode=episode)
    if not sources:
        raise HTTPException(404, "No subtitles are available for this selection.")
    captions = await service.subtitles.list(movie.id, movie.detail_path, sources[0].id)
    caption = next((item for item in captions if item.language == language), None)
    if caption is None:
        raise HTTPException(404, "This subtitle language is not available.")
    data = await service.subtitles.fetch(caption)
    title = movie.title + (f" S{season:02d}E{episode:02d}" if movie.kind == "series" else "")
    _, filename = source_name("https://example.org/video.mp4", title)
    filename = filename.removesuffix(".mp4") + f".{caption.language}.srt"
    return Response(
        data,
        media_type="application/x-subrip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.get("/{movie_id}/details")
async def movie_details(movie_id: str, service: Catalog):
    return await service.details_service.get(movie_id)


@router.post("/{movie_id}/download", status_code=201)
async def download_movie(
    movie_id: str, body: MovieDownloadRequest, service: Catalog, manager: Manager
):
    details = await service.details_service.get(movie_id)
    episodes = selected_episodes(details, body)
    movie = details.movie
    preview_episode = body.episode or episodes[0]
    sources = await service.sources(
        movie.id, movie.detail_path, season=body.season, episode=preview_episode
    )
    source = next((item for item in sources if item.id == body.source_id), None)
    if source is None:
        raise HTTPException(409, "This source is no longer available. Choose a quality again.")
    entries = []
    for episode in episodes:
        title = movie.title[:105] + (f" ({movie.year})" if movie.year else "")
        if movie.kind == "series":
            title += f" S{body.season:02d}E{episode:02d}"
        title += f" [{source.quality}]"
        entries.append(
            (
                DownloadRequest(url=source.url, title=title),
                source.headers,
                {
                    "movie_id": movie.id,
                    "detail_path": movie.detail_path,
                    "quality": source.quality,
                    "season": str(body.season),
                    "episode": str(episode),
                },
            )
        )
    jobs = await manager.add_batch(entries)
    return {"downloads": [job.public() for job in jobs]}
