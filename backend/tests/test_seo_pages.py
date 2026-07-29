"""SSR 공개 페이지(SEO) 회귀 — /search 초기 목록과 /bid 상태코드.

배경: 정적 /search 셸에는 공고 링크가 하나도 없어 크롤러가 /bid/* 로 갈 내부
경로가 없었고, 없는 공고는 200+noindex(soft-404)로 응답했다.
"""
from datetime import datetime, timedelta

import pytest

from app.api.v1.endpoints import pages
from app.db import models


NOW_KST = datetime(2026, 7, 16, 9, 0)


@pytest.fixture
def frozen_now(monkeypatch):
    monkeypatch.setattr(pages, "_current_naive_kst", lambda: NOW_KST)
    return NOW_KST


@pytest.fixture
def no_remote_fetch(monkeypatch):
    """`_resolve_notice` 의 OpenAPI 폴백을 막는다(테스트가 외부망을 타지 않도록)."""
    def _boom(bid_no, db):
        raise RuntimeError("remote fetch disabled in tests")

    monkeypatch.setattr(pages, "get_bid_context", _boom)


def _notice(bid_no, *, days_left, title="테스트 공고", **kw):
    return models.Notice(
        bid_no=bid_no,
        title=title,
        basic_price=kw.pop("basic_price", 1_000_000),
        start_date=NOW_KST - timedelta(days=1),
        end_date=NOW_KST + timedelta(days=days_left),
        **kw,
    )


def test_search_page_renders_bid_links_in_deadline_order(client, db_session, frozen_now):
    db_session.query(models.Notice).delete()
    db_session.add_all(
        [
            _notice("SSR-LATE-001", days_left=9, title="늦게 마감"),
            _notice("SSR-SOON-002", days_left=1, title="곧 마감"),
            # 마감된 공고는 노출 대상이 아니다.
            _notice("SSR-CLOSED-003", days_left=-1, title="이미 마감"),
        ]
    )
    db_session.flush()

    response = client.get("/search")

    assert response.status_code == 200
    body = response.text
    assert '/bid/SSR-SOON-002' in body
    assert '/bid/SSR-LATE-001' in body
    assert 'SSR-CLOSED-003' not in body
    # 마감 임박순 — 곧 마감이 먼저.
    assert body.index("SSR-SOON-002") < body.index("SSR-LATE-001")


def test_search_page_caps_initial_list(client, db_session, frozen_now, monkeypatch):
    monkeypatch.setattr(pages, "SEARCH_SSR_LIMIT", 2)
    db_session.query(models.Notice).delete()
    db_session.add_all([_notice(f"SSR-CAP-{i:03d}", days_left=i + 1) for i in range(5)])
    db_session.flush()

    response = client.get("/search")

    assert response.text.count('href="/bid/') == 2


def test_search_page_survives_empty_notice_table(client, db_session, frozen_now):
    db_session.query(models.Notice).delete()
    db_session.flush()

    response = client.get("/search")

    assert response.status_code == 200
    assert 'href="/bid/' not in response.text


def test_bid_page_returns_404_for_unknown_notice(client, db_session, no_remote_fetch):
    db_session.query(models.Notice).delete()
    db_session.flush()

    response = client.get("/bid/NO-SUCH-NOTICE-001")

    # soft-404(200+noindex) 대신 실제 404 — purge 로 사라진 URL 을 색인에서 빼기 위함.
    assert response.status_code == 404
    assert 'name="robots" content="noindex"' in response.text


def test_bid_page_marks_closed_notice_but_keeps_it_indexable(
    client, db_session, frozen_now, no_remote_fetch
):
    db_session.query(models.Notice).delete()
    db_session.add(_notice("SSR-CLOSED-200", days_left=-3, title="마감된 공고입니다"))
    db_session.flush()

    response = client.get("/bid/SSR-CLOSED-200")

    assert response.status_code == 200
    assert "마감된 공고" in response.text
    assert 'name="robots" content="noindex"' not in response.text


def test_bid_page_renders_active_notice_without_closed_notice(
    client, db_session, frozen_now, no_remote_fetch
):
    db_session.query(models.Notice).delete()
    db_session.add(_notice("SSR-OPEN-200", days_left=5, title="진행중 공고"))
    db_session.flush()

    response = client.get("/bid/SSR-OPEN-200")

    assert response.status_code == 200
    assert "진행중 공고" in response.text
    assert "마감된 공고" not in response.text
