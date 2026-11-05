"""Discover usable IPv4 addresses for development server links."""

import ipaddress
import socket


def network_addresses() -> list[str]:
    candidates: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # UDP connect selects the default interface without sending a packet.
            probe.connect(("192.0.2.1", 80))
            candidates.append(probe.getsockname()[0])
    except OSError:
        pass

    try:
        records = socket.getaddrinfo(
            socket.gethostname(), None, family=socket.AF_INET, type=socket.SOCK_STREAM
        )
        candidates.extend(record[4][0] for record in records)
    except OSError:
        pass

    addresses = []
    for candidate in dict.fromkeys(candidates):
        address = ipaddress.ip_address(candidate)
        if not (address.is_loopback or address.is_unspecified or address.is_link_local):
            addresses.append(candidate)
    return addresses
