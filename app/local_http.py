"""Loopback-only HTTP transport, independent of system/environment proxies."""
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from app.http_access import is_loopback


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_local_url(request, timeout: float):
    url = request.full_url if isinstance(request, Request) else request
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not is_loopback(parsed.hostname or ""):
        raise ValueError("Local transport only accepts loopback HTTP URLs.")
    return build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout)
