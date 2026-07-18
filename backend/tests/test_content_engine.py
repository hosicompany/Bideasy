"""
콘텐츠 엔진 Phase 1 테스트 (2026-07-19)
=========================================
주제 큐 → 구조화 정본 블록 → 결정적 렌더 → 검수 게이트 초안.
"""
import pytest

from app.db import models
from app.services import content_engine as ce


SAMPLE_BLOCKS = {
    "track": "knowledge",
    "topic_code": "K1",
    "title": "100개사가 몰려도 낙찰이 '실력'이 아닌 이유",
    "target_keyword": "사정률 추첨",
    "hook": "100개사가 몰린 공고, 낙찰자는 어떻게 정해질까요?",
    "summary_30s": "예정가격은 추첨으로 정해져요. 그래서 예측이 아니라 안전이 중요해요.",
    "key_points": [
        {"heading": "사정률 추첨의 원리", "body": "예비가격 15개 중 4개를 무작위로 뽑아요."},
        {"heading": "그래서 중요한 것", "body": "하한선 위 안전 투찰이 핵심이에요."},
    ],
    "data_blocks": [],
    "internal_links": ["/calculator"],
    "cta": "계산기로 안전 투찰가를 확인해보세요.",
    "seo_summary": "사정률 추첨 원리를 3분에 정리했어요.",
}


class TestTopicQueue:
    def test_seeds_integrity(self):
        """시드 24개, 코드 유니크, 필수 필드 존재."""
        assert len(ce.TOPIC_SEEDS) == 24
        codes = [t["code"] for t in ce.TOPIC_SEEDS]
        assert len(set(codes)) == 24
        for t in ce.TOPIC_SEEDS:
            assert t["title"] and t["angle"] and t["priority"] in ("P1", "P2", "P3")

    def test_no_forbidden_word_in_seeds(self):
        """전역 금지: 시드 제목·앵글에 '낙찰률' 표현 없음."""
        for t in ce.TOPIC_SEEDS:
            assert "낙찰률" not in t["title"] and "낙찰률" not in t["angle"]

    def test_list_topics_marks_existing_draft(self, db_session):
        db_session.query(models.BlogPost).filter(
            models.BlogPost.slug == ce.slug_for("K1")
        ).delete()
        db_session.add(models.BlogPost(
            slug=ce.slug_for("K1"), title="t", body_md="b", body_html="<p>b</p>",
        ))
        db_session.commit()
        topics = {t["code"]: t for t in ce.list_topics(db_session)}
        assert topics["K1"]["draft_exists"] is True
        assert topics["K2"]["draft_exists"] is False


class TestRender:
    def test_deterministic_and_complete(self):
        md1 = ce.render_blocks_to_md(SAMPLE_BLOCKS)
        md2 = ce.render_blocks_to_md(SAMPLE_BLOCKS)
        assert md1 == md2  # 결정적
        assert "30초 요약" in md1
        assert "## 사정률 추첨의 원리" in md1
        assert "계산기로 안전 투찰가" in md1


class TestCreateDraft:
    @pytest.fixture
    def mock_llm(self, monkeypatch):
        monkeypatch.setattr(ce, "generate_blocks", lambda topic: dict(SAMPLE_BLOCKS))

    def _cleanup(self, db, code):
        db.query(models.BlogPost).filter(
            models.BlogPost.slug == ce.slug_for(code)
        ).delete()
        db.commit()

    def test_creates_draft_with_review_gate(self, db_session, mock_llm):
        self._cleanup(db_session, "K1")
        post, status = ce.create_draft_from_topic(db_session, "K1")
        assert status == "created"
        assert post.status == "draft"
        assert post.publish_at is None          # 검수 게이트 — 자동발행 없음
        assert post.source == "auto"
        assert post.blocks_json["topic_code"] == "K1"
        assert "30초 요약" in post.body_md      # 블록→본문 렌더됨
        assert post.category == "입찰상식"

    def test_idempotent(self, db_session, mock_llm):
        self._cleanup(db_session, "K2")
        p1, s1 = ce.create_draft_from_topic(db_session, "K2")
        p2, s2 = ce.create_draft_from_topic(db_session, "K2")
        assert s1 == "created" and s2 == "exists"
        assert p1.id == p2.id

    def test_unknown_topic(self, db_session):
        post, status = ce.create_draft_from_topic(db_session, "K999")
        assert post is None and status == "unknown_topic"

    def test_no_llm_key_honest_failure(self, db_session, monkeypatch):
        """LLM 키 없으면 지어낸 폴백 초안을 만들지 않는다 (정직)."""
        self._cleanup(db_session, "K3")
        monkeypatch.setattr(ce.settings, "OPENAI_API_KEY", "")
        post, status = ce.create_draft_from_topic(db_session, "K3")
        assert post is None and status == "llm_unavailable"


class TestAdminEndpoints:
    def test_topics_endpoint(self, admin_client):
        res = admin_client.get("/api/v1/admin/blog/topics")
        assert res.status_code == 200
        assert len(res.json()["topics"]) == 24

    def test_generate_endpoint_llm_unavailable_503(self, admin_client, monkeypatch):
        monkeypatch.setattr(ce.settings, "OPENAI_API_KEY", "")
        res = admin_client.post("/api/v1/admin/blog/generate-from-topic/K4")
        assert res.status_code == 503

    def test_generate_endpoint_success(self, admin_client, db_session, monkeypatch):
        db_session.query(models.BlogPost).filter(
            models.BlogPost.slug == ce.slug_for("K5")
        ).delete()
        db_session.commit()
        monkeypatch.setattr(ce, "generate_blocks", lambda topic: dict(SAMPLE_BLOCKS))
        res = admin_client.post("/api/v1/admin/blog/generate-from-topic/k5")  # 소문자 수용
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "draft"
        assert data["publish_at"] is None
        assert data["blocks_json"]["hook"]

    def test_requires_admin(self, client):
        assert client.get("/api/v1/admin/blog/topics").status_code in (401, 403)


class TestDataStoryBlocksAlignment:
    def test_weekly_story_carries_blocks(self, db_session):
        """데이터스토리 초안에 blocks_json 정합 (숫자 결정적)."""
        from datetime import datetime, timedelta
        from app.services import data_story

        db_session.query(models.OpeningResult).delete()
        db_session.query(models.BlogPost).delete()
        db_session.commit()
        ref = datetime(2026, 7, 15)
        mon = ref - timedelta(days=ref.weekday() + 7)
        db_session.add(models.OpeningResult(
            bid_no="CE-DS-1", organization="테스트기관", region="서울",
            open_date=mon + timedelta(days=1), basic_price=1e8,
            reserved_price=1.005e8, bid_method="적격심사제",
            winner_company="업체A", winner_price=8.8e7, winner_rate=88.0,
            participants_count=42,
        ))
        db_session.commit()
        post, status = data_story.create_weekly_draft(db_session, ref.date())
        assert status == "created"
        blocks = post.blocks_json
        assert blocks["track"] == "data_story"
        assert blocks["data_blocks"][0]["numbers"][0]["participants"] == 42  # DB 결정적
