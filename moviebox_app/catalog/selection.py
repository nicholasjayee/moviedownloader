"""Validate an entire episode selection before any downloads are queued."""

from moviebox_app.catalog.models import MediaDetails, MovieDownloadRequest


def selected_episodes(details: MediaDetails, request: MovieDownloadRequest) -> list[int]:
    if details.movie.kind == "movie":
        if request.season or request.episode or request.episodes or request.all_episodes:
            raise ValueError("Episode selection is only available for series.")
        return [0]

    season = next((item for item in details.seasons if item.number == request.season), None)
    if season is None:
        raise ValueError("Choose a valid season.")
    episodes = (
        list(range(1, season.episodes + 1))
        if request.all_episodes
        else request.episodes or [request.episode]
    )
    if any(number < 1 or number > season.episodes for number in episodes):
        raise ValueError(f"Choose episodes between 1 and {season.episodes} for this season.")
    if request.episode and request.episode not in episodes:
        raise ValueError("The preview episode must be one of the selected episodes.")
    return episodes
