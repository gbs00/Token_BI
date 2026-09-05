from __future__ import annotations

import ipaddress
from typing import Optional
from urllib.parse import urlsplit


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
        return (getattr(address, "ipv4_mapped", None) or address).is_loopback
    except ValueError:
        return False


def allows_local_management(client_host: str, host: str, origin: Optional[str]) -> bool:
    try:
        return (is_loopback(client_host) and is_loopback(host)
                and (origin is None or is_loopback(urlsplit(origin).hostname or "")))
    except ValueError:
        return False
