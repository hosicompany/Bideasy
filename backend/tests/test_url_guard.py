"""SSRF 가드(url_guard) 단위 테스트."""
import pytest

from app.core import url_guard
from app.core.url_guard import is_safe_public_url, assert_safe_url, UnsafeUrlError


@pytest.fixture
def public_dns(monkeypatch):
    """화이트리스트 호스트가 공인 IP 로 해석된다고 가정 (네트워크 비의존)."""
    monkeypatch.setattr(url_guard, "_resolved_ips_are_public", lambda host: True)


def test_allows_whitelisted_domain(public_dns):
    assert is_safe_public_url("https://www.g2b.go.kr/some/notice") is True
    assert is_safe_public_url("https://apis.data.go.kr/x") is True


def test_blocks_metadata_and_internal(public_dns):
    # 화이트리스트에 없는 호스트는 도메인 단계에서 차단
    assert is_safe_public_url("http://169.254.169.254/latest/meta-data/") is False
    assert is_safe_public_url("http://localhost:6379/") is False
    assert is_safe_public_url("http://10.0.0.5/internal") is False
    assert is_safe_public_url("http://attacker.com/g2b.go.kr") is False


def test_blocks_non_http_schemes(public_dns):
    assert is_safe_public_url("file:///etc/passwd") is False
    assert is_safe_public_url("gopher://www.g2b.go.kr/") is False
    assert is_safe_public_url("ftp://www.g2b.go.kr/") is False


def test_blocks_lookalike_domain(public_dns):
    # 접미사 우회 시도 (g2b.go.kr.attacker.com)
    assert is_safe_public_url("https://www.g2b.go.kr.attacker.com/") is False


def test_blocks_private_ip_even_if_whitelisted_name(monkeypatch):
    # 화이트리스트 도메인이지만 사설 IP 로 해석되면(DNS rebinding) 차단
    monkeypatch.setattr(url_guard, "_resolved_ips_are_public", lambda host: False)
    assert is_safe_public_url("https://www.g2b.go.kr/") is False


def test_assert_raises(public_dns):
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("http://169.254.169.254/")
    assert assert_safe_url("https://www.g2b.go.kr/ok") == "https://www.g2b.go.kr/ok"


def test_empty_and_none():
    assert is_safe_public_url("") is False
    assert is_safe_public_url(None) is False
