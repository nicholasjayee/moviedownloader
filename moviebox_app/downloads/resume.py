"""Validate HTTP range responses before appending to a partial video."""

import re

from moviebox_app.models import Download


def range_total(job: Download, response, offset: int) -> int:
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
    if match:
        start, end, total = map(int, match.groups())
        valid = start == offset and offset <= end < total
        valid = valid and response.content_length in {None, end - start + 1}
        valid = valid and (job.total_bytes is None or total == job.total_bytes)
        if job.etag and response.headers.get("ETag"):
            valid = valid and response.headers["ETag"] == job.etag
        if valid:
            return total
    job.etag, job.last_modified = "", ""
    raise ValueError(
        "Source returned an invalid resume response. Retry to start from the beginning."
    )
