"""A series batch starts with one preview URL; identify jobs by episode and quality."""


def source_key(url: str, provider: dict[str, str]) -> tuple[str, ...]:
    if provider:
        return (
            "moviebox",
            *(
                provider.get(key, "")
                for key in (
                    "movie_id",
                    "season",
                    "episode",
                    "quality",
                )
            ),
        )
    return ("url", url)
