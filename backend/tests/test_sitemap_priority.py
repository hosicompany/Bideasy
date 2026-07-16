"""동적 sitemap의 공고 선택 순서와 XML 메타데이터 회귀 테스트."""
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

from app.api.v1.endpoints.pages import _current_naive_kst
from app.db import models


SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
STATIC_URLS = [
    "https://bideasy.kr",
    "https://bideasy.kr/search",
    "https://bideasy.kr/calculator",
    "https://bideasy.kr/guide",
    "https://bideasy.kr/pricing",
    "https://bideasy.kr/blog",
]


def _urls(response):
    root = ElementTree.fromstring(response.content)
    return [
        {
            "loc": node.findtext("sm:loc", namespaces=SITEMAP_NS),
            "lastmod": node.findtext("sm:lastmod", namespaces=SITEMAP_NS),
        }
        for node in root.findall("sm:url", SITEMAP_NS)
    ]


def test_current_naive_kst_converts_aware_instant_and_removes_timezone():
    utc_instant = datetime(2026, 7, 15, 18, 30, 45, tzinfo=timezone.utc)

    result = _current_naive_kst(utc_instant)

    assert result == datetime(2026, 7, 16, 3, 30, 45)
    assert result.tzinfo is None


def test_sitemap_selects_highest_50_bid_numbers_independent_of_start_date(
    client, db_session, monkeypatch
):
    # Other tests commit synthetic notices; isolate this selection test from their rows.
    db_session.query(models.Notice).delete()
    now_kst = datetime(2026, 7, 16, 9, 0)
    active_end = now_kst + timedelta(days=1)
    notices = [
        models.Notice(
            bid_no=f"99999999{index:04d}-00",
            title=f"sitemap test {index}",
            basic_price=1,
            # Deliberately inverse to bid_no: collection time must not control selection/order.
            start_date=now_kst - timedelta(minutes=index),
            end_date=active_end,
        )
        for index in range(52)
    ]
    notices.extend(
        [
            models.Notice(
                bid_no="999999999999-01",
                title="null start",
                basic_price=1,
                start_date=None,
                end_date=active_end,
            ),
            models.Notice(
                bid_no="999999999999-02",
                title="null end",
                basic_price=1,
                start_date=now_kst,
                end_date=None,
            ),
            models.Notice(
                bid_no="999999999999-03",
                title="expired",
                basic_price=1,
                start_date=now_kst,
                end_date=now_kst,
            ),
        ]
    )
    db_session.add_all(notices)
    db_session.flush()
    monkeypatch.setattr(
        "app.api.v1.endpoints.pages._current_naive_kst", lambda: now_kst
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.pages.blog_svc.list_posts",
        lambda db: [
            {"slug": "published-one", "updated": "2026-07-15"},
            {"slug": "published&two", "date": "2026-07-14"},
        ],
    )

    response = client.get("/sitemap.xml")
    repeated = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.content == repeated.content
    urls = _urls(response)
    assert [entry["loc"] for entry in urls[:6]] == STATIC_URLS
    assert [entry["loc"] for entry in urls[6:8]] == [
        "https://bideasy.kr/blog/published-one",
        "https://bideasy.kr/blog/published&two",
    ]
    assert [entry["lastmod"] for entry in urls[6:8]] == ["2026-07-15", "2026-07-14"]

    bids = [entry for entry in urls if "/bid/" in (entry["loc"] or "")]
    assert len(bids) == 50
    assert [entry["loc"] for entry in bids] == [
        f"https://bideasy.kr/bid/99999999{index:04d}-00"
        for index in range(51, 1, -1)
    ]
    assert all(entry["lastmod"] is None for entry in bids)
    assert "999999999999-01" not in response.text
    assert "999999999999-02" not in response.text
    assert "999999999999-03" not in response.text
    assert "999999990001-00" not in response.text
    assert "999999990002-00" in response.text
    assert "published&amp;two" in response.text


def test_sitemap_has_daily_shared_cache_headers(client):
    response = client.get("/sitemap.xml")

    assert response.headers["cache-control"] == (
        "public, max-age=3600, s-maxage=86400, stale-while-revalidate=3600"
    )
