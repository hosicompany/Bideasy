"""동적 sitemap의 구조·공고 선택 순서와 XML 메타데이터 회귀 테스트."""
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

from app.api.v1.endpoints import pages
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


def _child_sitemaps(response):
    root = ElementTree.fromstring(response.content)
    return [node.findtext("sm:loc", namespaces=SITEMAP_NS) for node in root.findall("sm:sitemap", SITEMAP_NS)]


def _seed_active_notices(db_session, count, *, now_kst, prefix="99999999"):
    db_session.query(models.Notice).delete()
    active_end = now_kst + timedelta(days=1)
    notices = [
        models.Notice(
            bid_no=f"{prefix}{index:04d}-00",
            title=f"sitemap test {index}",
            basic_price=1,
            # Deliberately inverse to bid_no: collection time must not control selection/order.
            start_date=now_kst - timedelta(minutes=index),
            end_date=active_end,
        )
        for index in range(count)
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


def test_current_naive_kst_converts_aware_instant_and_removes_timezone():
    utc_instant = datetime(2026, 7, 15, 18, 30, 45, tzinfo=timezone.utc)

    result = _current_naive_kst(utc_instant)

    assert result == datetime(2026, 7, 16, 3, 30, 45)
    assert result.tzinfo is None


def test_sitemap_index_lists_static_blog_and_chunked_notice_children(
    client, db_session, monkeypatch
):
    now_kst = datetime(2026, 7, 16, 9, 0)
    # Two full chunks + 1 → 3 notice sitemaps.
    monkeypatch.setattr(pages, "SITEMAP_CHUNK", 4)
    _seed_active_notices(db_session, 9, now_kst=now_kst)
    monkeypatch.setattr(pages, "_current_naive_kst", lambda: now_kst)

    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert _child_sitemaps(response) == [
        "https://bideasy.kr/sitemap-static.xml",
        "https://bideasy.kr/sitemap-blog.xml",
        "https://bideasy.kr/sitemap-notices-1.xml",
        "https://bideasy.kr/sitemap-notices-2.xml",
        "https://bideasy.kr/sitemap-notices-3.xml",
    ]


def test_sitemap_index_keeps_one_notice_child_when_no_active_notices(
    client, db_session, monkeypatch
):
    db_session.query(models.Notice).delete()
    db_session.flush()

    response = client.get("/sitemap.xml")

    assert _child_sitemaps(response) == [
        "https://bideasy.kr/sitemap-static.xml",
        "https://bideasy.kr/sitemap-blog.xml",
        "https://bideasy.kr/sitemap-notices-1.xml",
    ]


def test_sitemap_static_lists_public_pages(client):
    response = client.get("/sitemap-static.xml")

    assert response.status_code == 200
    assert [entry["loc"] for entry in _urls(response)] == STATIC_URLS


def test_sitemap_blog_lists_published_posts_with_lastmod(client, monkeypatch):
    monkeypatch.setattr(
        pages.blog_svc,
        "list_posts",
        lambda db: [
            {"slug": "published-one", "updated": "2026-07-15"},
            {"slug": "published&two", "date": "2026-07-14"},
        ],
    )

    response = client.get("/sitemap-blog.xml")

    urls = _urls(response)
    assert [entry["loc"] for entry in urls] == [
        "https://bideasy.kr/blog/published-one",
        "https://bideasy.kr/blog/published&two",
    ]
    assert [entry["lastmod"] for entry in urls] == ["2026-07-15", "2026-07-14"]
    assert "published&amp;two" in response.text


def test_sitemap_notices_pages_cover_every_active_notice_in_bid_no_order(
    client, db_session, monkeypatch
):
    now_kst = datetime(2026, 7, 16, 9, 0)
    monkeypatch.setattr(pages, "SITEMAP_CHUNK", 4)
    _seed_active_notices(db_session, 9, now_kst=now_kst)
    monkeypatch.setattr(pages, "_current_naive_kst", lambda: now_kst)

    first = client.get("/sitemap-notices-1.xml")
    second = client.get("/sitemap-notices-2.xml")
    third = client.get("/sitemap-notices-3.xml")
    repeated_first = client.get("/sitemap-notices-1.xml")

    assert first.content == repeated_first.content
    collected = [
        entry["loc"] for page in (first, second, third) for entry in _urls(page)
    ]
    # 50건 상한이 사라졌다: 진행중 공고 전량이 chunk 로 나뉘어 전부 실린다.
    assert collected == [
        f"https://bideasy.kr/bid/99999999{index:04d}-00" for index in range(8, -1, -1)
    ]
    assert len(_urls(first)) == 4 and len(_urls(third)) == 1
    assert all(entry["lastmod"] is None for entry in _urls(first))
    # 마감·start/end 결측 공고는 제외.
    for excluded in ("999999999999-01", "999999999999-02", "999999999999-03"):
        assert excluded not in first.text + second.text + third.text


def test_sitemap_notices_page_beyond_range_returns_empty_urlset(client, db_session):
    db_session.query(models.Notice).delete()
    db_session.flush()

    response = client.get("/sitemap-notices-99.xml")

    assert response.status_code == 200
    assert _urls(response) == []


def test_sitemaps_have_daily_shared_cache_headers(client):
    for path in ("/sitemap.xml", "/sitemap-static.xml", "/sitemap-blog.xml", "/sitemap-notices-1.xml"):
        response = client.get(path)

        assert response.headers["cache-control"] == (
            "public, max-age=3600, s-maxage=86400, stale-while-revalidate=3600"
        ), path
