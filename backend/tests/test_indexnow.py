"""IndexNow 통보 서비스 — 안전장치(비활성·상한·비치명성) 회귀."""
import pytest

from app.core.config import settings
from app.services import indexnow


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "INDEXNOW_KEY", "testkey0123456789")
    monkeypatch.setattr(settings, "INDEXNOW_ENDPOINTS", ["https://engine.test/indexnow"])


@pytest.fixture
def captured(monkeypatch):
    """httpx.post 를 가로채 발송 payload 를 수집(실제 네트워크 금지)."""
    calls = []

    class _Resp:
        status_code = 200

    def _fake_post(url, **kwargs):
        calls.append({"url": url, "json": kwargs.get("json")})
        return _Resp()

    monkeypatch.setattr(indexnow.httpx, "post", _fake_post)
    return calls


def test_disabled_outside_production(monkeypatch, captured):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "INDEXNOW_KEY", "testkey0123456789")

    result = indexnow.submit([f"{indexnow.SITE_URL}/blog/x"])

    # dev/test 에서 실제 검색엔진으로 나가면 안 된다.
    assert result == {"skipped": "disabled", "count": 0}
    assert captured == []


def test_disabled_without_key(monkeypatch, captured):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "INDEXNOW_KEY", "")

    assert indexnow.submit([f"{indexnow.SITE_URL}/blog/x"])["skipped"] == "disabled"
    assert captured == []


def test_submits_payload_with_key_location(enabled, captured):
    result = indexnow.submit(indexnow.blog_urls(["hello"]), reason="test")

    assert result["count"] == 1
    assert len(captured) == 1
    body = captured[0]["json"]
    assert body["host"] == "bideasy.kr"
    assert body["key"] == "testkey0123456789"
    assert body["keyLocation"] == "https://bideasy.kr/testkey0123456789.txt"
    assert body["urlList"] == ["https://bideasy.kr/blog/hello"]


def test_drops_foreign_hosts_and_duplicates(enabled, captured):
    result = indexnow.submit([
        "https://bideasy.kr/bid/A-1",
        "https://bideasy.kr/bid/A-1",       # 중복
        "https://evil.example.com/bid/A-2",  # 타 호스트
        "",                                  # 빈 값
    ])

    assert result["count"] == 1
    assert captured[0]["json"]["urlList"] == ["https://bideasy.kr/bid/A-1"]


def test_caps_total_urls_per_run(enabled, captured, monkeypatch):
    monkeypatch.setattr(indexnow, "MAX_PER_RUN", 3)

    result = indexnow.submit(indexnow.notice_urls([f"BID-{i}" for i in range(10)]))

    assert result["count"] == 3
    assert len(captured[0]["json"]["urlList"]) == 3


def test_max_urls_override_bypasses_default_cap(enabled, captured, monkeypatch):
    """일회성 일괄 통보는 전량 발송이 목적 — 자동 훅용 상한에 잘리면 안 된다."""
    monkeypatch.setattr(indexnow, "MAX_PER_RUN", 3)
    urls = indexnow.notice_urls([f"BID-{i}" for i in range(10)])

    result = indexnow.submit(urls, max_urls=len(urls))

    assert result["count"] == 10
    assert len(captured[0]["json"]["urlList"]) == 10


def test_chunks_at_protocol_limit(enabled, captured, monkeypatch):
    monkeypatch.setattr(indexnow, "CHUNK_SIZE", 4)
    urls = indexnow.notice_urls([f"BID-{i}" for i in range(9)])

    indexnow.submit(urls, max_urls=len(urls))

    # 엔드포인트 1개 × 3청크(4+4+1)
    assert [len(c["json"]["urlList"]) for c in captured] == [4, 4, 1]


def test_no_urls_is_not_an_error(enabled, captured):
    assert indexnow.submit([])["skipped"] == "no_urls"
    assert captured == []


def test_network_failure_never_raises(enabled, monkeypatch):
    def _boom(url, **kwargs):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(indexnow.httpx, "post", _boom)

    # 통보 실패가 호출부(발행·수집)를 되돌리면 안 된다.
    result = indexnow.submit(indexnow.blog_urls(["x"]))

    assert result["count"] == 1
    assert "error" in str(result["results"])


def test_non_2xx_response_is_recorded_not_raised(enabled, monkeypatch):
    class _Resp:
        status_code = 403  # 잘못된 키

    monkeypatch.setattr(indexnow.httpx, "post", lambda url, **kw: _Resp())

    result = indexnow.submit(indexnow.blog_urls(["x"]))

    assert result["results"]["https://engine.test/indexnow"] == "403"


def test_url_builders_skip_empty_values():
    assert indexnow.notice_urls(["A", "", None]) == ["https://bideasy.kr/bid/A"]
    assert indexnow.blog_urls(["s", None]) == ["https://bideasy.kr/blog/s"]


def test_config_key_matches_published_key_file():
    """키 파일과 config 기본값이 어긋나면 소유 증명이 깨진다(403)."""
    from pathlib import Path

    key = "1ba9903f6def627dc5124779539223ee"
    assert settings.INDEXNOW_KEY == key
    key_file = (
        Path(__file__).resolve().parents[2] / "infra" / "nginx" / "html" / f"{key}.txt"
    )
    assert key_file.is_file(), f"키 파일 없음: {key_file}"
    assert key_file.read_text(encoding="utf-8").strip() == key
