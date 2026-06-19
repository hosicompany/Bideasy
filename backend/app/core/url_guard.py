"""SSRF 방어용 URL 검증 가드.

외부에서 fetch 하는 모든 URL(공고 페이지 재스크래핑, 첨부 다운로드)은
이 모듈을 통과해야 한다. 사용자가 notice_url/attachment_url 을 직접 제어할 수
있으므로(쿼리 파라미터), 내부망·클라우드 메타데이터(169.254.169.254) 등으로의
서버측 요청(SSRF)을 차단한다.

정책:
  1. scheme 는 http/https 만 허용.
  2. 호스트가 사설/루프백/링크로컬/예약 IP 로 해석되면 거부.
  3. 도메인 화이트리스트(조달청·공공데이터)만 허용.
"""
import ipaddress
import socket
from urllib.parse import urlparse

from app.core.logging import get_logger

logger = get_logger(__name__)

# 조달청/공공데이터 관련 허용 도메인 (서브도메인 포함).
ALLOWED_HOST_SUFFIXES = (
    "g2b.go.kr",
    "data.go.kr",
    "narajangter.go.kr",
    "nara.go.kr",
)


class UnsafeUrlError(ValueError):
    """SSRF 위험으로 차단된 URL."""


def _host_is_allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == suf or host.endswith("." + suf) for suf in ALLOWED_HOST_SUFFIXES)


def _resolved_ips_are_public(host: str) -> bool:
    """host 의 모든 해석 IP 가 공인 대역인지 확인 (DNS rebinding 일부 완화)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def is_safe_public_url(url: str) -> bool:
    """fetch 해도 안전한(SSRF 아닌) URL 인지 검사. 화이트리스트 도메인 + 공인 IP."""
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    if not _host_is_allowed(host):
        return False
    if not _resolved_ips_are_public(host):
        return False
    return True


def assert_safe_url(url: str) -> str:
    """안전하지 않으면 UnsafeUrlError 를 던지고, 안전하면 url 을 그대로 반환."""
    if not is_safe_public_url(url):
        logger.warning(f"Blocked unsafe fetch URL (SSRF guard): {url!r}")
        raise UnsafeUrlError(f"허용되지 않은 URL: {url}")
    return url
