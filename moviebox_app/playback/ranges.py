import re

from moviebox_app.catalog.models import CatalogError


def validate_video_range(requested: str | None, content_range: str, length: int | None) -> None:
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
    if not requested or not match:
        raise CatalogError("The source returned an invalid video range.")
    start, end, total = map(int, match.groups())
    first, last = requested.removeprefix("bytes=").split("-", 1)
    expected_start = int(first) if first else max(0, total - int(last))
    valid = start == expected_start and start <= end < total
    if first and last:
        valid = valid and end <= int(last)
    if length is not None:
        valid = valid and length == end - start + 1
    if not valid:
        raise CatalogError("The source returned an invalid video range.")
