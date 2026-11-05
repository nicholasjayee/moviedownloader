import ipaddress
import socket
from urllib.parse import urlsplit

from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver


def validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use a full HTTP or HTTPS media URL.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not supported.")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("Only standard HTTP and HTTPS ports are supported.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname.lower() == "localhost" or parsed.hostname.lower().endswith(".localhost"):
            raise ValueError("Local and private network addresses are blocked.") from None
    else:
        if not address.is_global:
            raise ValueError("Local and private network addresses are blocked.")


class PublicResolver(AbstractResolver):
    """Validate the actual DNS results used by the connector, including redirects."""

    def __init__(self):
        self.resolver = DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        records = await self.resolver.resolve(host, port, family)
        if not records or any(not ipaddress.ip_address(row["host"]).is_global for row in records):
            raise OSError("Local and private network addresses are blocked.")
        return records

    async def close(self) -> None:
        await self.resolver.close()
