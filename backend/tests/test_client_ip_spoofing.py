"""X-Forwarded-For 위조로 레이트리밋을 우회할 수 없어야 한다.

nginx 는 `$proxy_add_x_forwarded_for` 로 실 IP 를 맨 뒤에 붙인다. 공격자가 보낸 값은
그 앞에 남으므로, 요청자 판정은 마지막 홉이어야 한다.
"""

from __future__ import annotations

import asyncio

from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.rate_limit import _key_func
from main import TRUSTED_PROXIES

NGINX_PEER = ("172.18.0.5", 12345)  # 도커 브리지에서 붙는 nginx


def _request(xff: str | None, peer=NGINX_PEER) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": peer, "path": "/", "method": "GET"})


def test_rate_limit_key_ignores_spoofed_prefix():
    # 공격자가 매 요청마다 앞자리를 바꿔도 키는 nginx 가 붙인 실 IP 로 같다.
    assert _key_func(_request("1.1.1.1, 203.0.113.7")) == "203.0.113.7"
    assert _key_func(_request("9.9.9.9, 203.0.113.7")) == "203.0.113.7"


def test_rate_limit_key_without_proxy_header():
    assert _key_func(_request(None, peer=("203.0.113.9", 1))) == "203.0.113.9"


def _client_after_proxy_middleware(xff: str, peer) -> str:
    seen = {}

    async def app(scope, receive, send):
        seen["client"] = scope["client"][0]

    mw = ProxyHeadersMiddleware(app, trusted_hosts=TRUSTED_PROXIES)
    scope = {"type": "http", "headers": [(b"x-forwarded-for", xff.encode())], "client": peer}
    asyncio.run(mw(scope, None, None))
    return seen["client"]


def test_proxy_middleware_uses_last_untrusted_hop():
    assert _client_after_proxy_middleware("1.1.1.1, 203.0.113.7", NGINX_PEER) == "203.0.113.7"


def test_proxy_middleware_ignores_header_from_untrusted_peer():
    # nginx 를 거치지 않고 직접 붙은 공인 IP 가 보낸 XFF 는 믿지 않는다.
    assert _client_after_proxy_middleware("1.1.1.1", ("198.51.100.4", 1)) == "198.51.100.4"
