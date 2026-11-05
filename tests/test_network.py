import socket

import pytest

from moviebox_app.downloads.network import PublicResolver, validate_url
from moviebox_app.storage.paths import source_name


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/movie.mp4",
        "http://10.0.0.1/movie.mp4",
        "http://169.254.169.254/latest",
        "http://[::1]/movie.mp4",
        "http://localhost/a",
        "https://example.org:8000/a",
        "https://user:secret@example.org/a",
    ],
)
def test_reject_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_url(url)


async def test_resolver_checks_addresses_used_for_connection(monkeypatch):
    resolver = PublicResolver()

    async def resolve(*args):
        return [
            {
                "hostname": "example.org",
                "host": "192.168.1.1",
                "port": 80,
                "family": socket.AF_INET,
                "proto": 0,
                "flags": 0,
            }
        ]

    monkeypatch.setattr(resolver.resolver, "resolve", resolve)
    try:
        with pytest.raises(OSError, match="private"):
            await resolver.resolve("example.org")
    finally:
        await resolver.close()


def test_filename_never_preserves_path_traversal():
    _, filename = source_name("https://example.org/a.mp4", "../../a/<script>")
    assert "/" not in filename
    assert "<" not in filename
    assert filename.endswith(".mp4")


def test_unicode_filename_fits_filesystem_component_limit():
    _, filename = source_name("https://example.org/a.mp4", "🎥电影" * 40)
    assert len(("a" * 32 + "_" + filename + ".part").encode("utf-8")) <= 255
