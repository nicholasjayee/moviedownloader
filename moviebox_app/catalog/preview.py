"""Normalize optional provider metadata without requiring trailers for every title."""

from urllib.parse import urlsplit

from moviebox_app.catalog.models import Trailer
from moviebox_app.downloads.network import validate_url


def public_media_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        if urlsplit(value).scheme != "https":
            return ""
        validate_url(value)
    except ValueError:
        return ""
    return value


def trailer_from_subject(subject: dict) -> Trailer | None:
    trailer = subject.get("trailer")
    if not isinstance(trailer, dict):
        return None
    address = trailer.get("videoAddress") or {}
    cover = trailer.get("cover") or {}
    if not isinstance(address, dict) or not isinstance(cover, dict):
        return None
    url = public_media_url(address.get("url"))
    return Trailer(url=url, poster=public_media_url(cover.get("url"))) if url else None


def cast_names(stars: object) -> list[str]:
    if not isinstance(stars, list):
        return []
    names = []
    for star in stars:
        if isinstance(star, dict) and str(star.get("staffType", 1)) == "1":
            name = star.get("name") or star.get("staffName")
            if isinstance(name, str) and name.strip() and name.strip() not in names:
                names.append(name.strip())
    return names[:20]
