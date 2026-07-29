"""수동 크롤링 엔드포인트 관리자 권한 회귀 테스트."""

import pytest


def _fail_if_crawler_runs(*_args, **_kwargs):
    raise AssertionError("권한 거부 요청에서 크롤러가 실행되면 안 됩니다.")


@pytest.mark.parametrize(
    ("fixture_name", "expected_status"),
    [("client", 401), ("free_client", 403)],
)
def test_manual_crawl_rejects_unauthorized_request_before_crawling(
    request,
    monkeypatch,
    fixture_name,
    expected_status,
):
    """비관리자 요청은 크롤러 실행 전에 인증·권한 단계에서 차단한다."""
    from app.services.crawler import CrawlerService

    monkeypatch.setattr(CrawlerService, "fetch_notices", _fail_if_crawler_runs)
    client = request.getfixturevalue(fixture_name)

    response = client.post("/api/v1/bids/crawl")

    assert response.status_code == expected_status
    if expected_status == 403:
        assert "관리자" in response.json()["detail"]
