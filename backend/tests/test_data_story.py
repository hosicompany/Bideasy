"""Track B 데이터 스토리 — 데이터 계산·초안 생성·멱등·수동 트리거.

LLM 서술은 monkeypatch 로 None(템플릿) 강제 → 네트워크 없이 결정적.
"""
from datetime import date, datetime, timedelta

import pytest

from app.db import models
from app.services import data_story


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr(data_story, "_llm_narrative", lambda ctx: None)


def _seed_week(db, mon: date, specs):
    """mon(월요일) 주에 OpeningResult 적재. specs=[(org, participants, rate, basic_price), ...]"""
    od = datetime(mon.year, mon.month, mon.day) + timedelta(days=1, hours=10)
    for i, (org, part, rate, price) in enumerate(specs):
        bid_no = f"OR-{mon.isoformat()}-{i}"
        if db.query(models.OpeningResult).filter(models.OpeningResult.bid_no == bid_no).first():
            continue
        db.add(models.OpeningResult(
            bid_no=bid_no, organization=org, region="서울",
            open_date=od, basic_price=price, winner_rate=rate, participants_count=part,
        ))
    db.commit()


def test_build_weekly_story_ranks_and_opportunities(db_session):
    ref = date(2025, 6, 16)
    mon, _ = data_story.last_completed_week(ref)
    _seed_week(db_session, mon, [
        ("A기관", 25, 87.9, 1_000_000_000),
        ("B기관", 3, 88.1, 500_000_000),
        ("C기관", 1, 0, 800_000_000),    # 단독
        ("D기관", 2, 86.7, 300_000_000),  # 저경쟁
        ("E기관", 12, 88.0, 200_000_000),
    ])
    story = data_story.build_weekly_story(db_session, ref_date=ref)
    assert story is not None
    assert story["slug"] == data_story.iso_week_slug(mon)
    assert "25개사" in story["body_md"]            # 최다 경쟁
    assert "단독·저경쟁" in story["body_md"]         # 기회 섹션
    assert story["period"]["count"] == 5
    assert story["period"]["opportunities"] == 2    # 참여 2 이하 = C,D


def test_no_data_returns_none(db_session):
    assert data_story.build_weekly_story(db_session, ref_date=date(2024, 1, 8)) is None


def test_create_weekly_draft_idempotent(db_session):
    ref = date(2025, 7, 21)
    mon, _ = data_story.last_completed_week(ref)
    _seed_week(db_session, mon, [("A", 10, 88.0, 1_000_000_000), ("B", 1, 0, 500_000_000)])
    post, status = data_story.create_weekly_draft(db_session, ref_date=ref)
    assert status == "created"
    assert post.status == "draft" and post.source == "auto"
    assert post.slug == data_story.iso_week_slug(mon)
    assert "<table>" in post.body_html              # 마크다운 표 렌더(파일과 동일 파이프라인)
    post2, status2 = data_story.create_weekly_draft(db_session, ref_date=ref)
    assert status2 == "exists" and post2.id == post.id


def test_generate_endpoint(admin_client, db_session, client):
    mon, _ = data_story.last_completed_week(date.today())
    _seed_week(db_session, mon, [("X기관", 30, 88.2, 2_000_000_000), ("Y기관", 1, 0, 700_000_000)])
    r = admin_client.post("/api/v1/admin/blog/generate-data-story")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "auto" and body["status"] == "draft"
    slug = body["slug"]
    assert slug not in client.get("/blog").text     # 초안 비공개
    admin_client.post(f"/api/v1/admin/blog/{body['id']}/publish")
    assert slug in client.get("/blog").text         # 발행 후 공개
