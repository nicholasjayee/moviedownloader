import aiohttp
from starlette.responses import StreamingResponse


class VideoResponse(StreamingResponse):
    """Release the upstream connection on completion, cancellation, or disconnect."""

    def __init__(self, upstream: aiohttp.ClientResponse, chunk_size: int, headers: dict[str, str]):
        self.upstream = upstream
        super().__init__(
            upstream.content.iter_chunked(chunk_size), status_code=upstream.status, headers=headers
        )

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.upstream.close()
