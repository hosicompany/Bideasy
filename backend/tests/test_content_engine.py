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

    def test_image_placeholders_commented_out(self):
        """이미지 자리는 주석 처리 — 파일 배치·눈검수 전엔 렌더에 안 나온다(§5.1)."""
        blocks = dict(SAMPLE_BLOCKS)
        blocks["image_prompts"] = [
            {"slot": "hero", "caption": "사정률 추첨 개념", "prompt": "deep blue abstract, no text"},
            {"slot": "diagram", "caption": "예정가격 추첨 흐름", "prompt": "Render the Korean text labels EXACTLY: ..."},
        ]
        md = ce.render_blocks_to_md(blocks, slug="knowledge-k1")
        assert "<!-- 이미지 자리(hero)" in md
        assert "/assets/blog/knowledge-k1/hero.png" in md
        assert "/assets/blog/knowledge-k1/fig1.png" in md
        # 이미지 마크다운은 전부 주석 블록 안 — 주석 열림/닫힘 쌍이 이미지 수만큼
        assert md.count("<!--") == 2 and md.count("-->") == 2
        # slug 없으면(구 호출 호환) 자리 미직조
        assert "이미지 자리" not in ce.render_blocks_to_md(blocks)


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


SAMPLE_ASSETS = {
    "instagram_cards": [
        {"kind": "cover", "badge": "입찰상식", "headline": "낙찰은\n실력이 아니에요", "body": "사정률 추첨", "fl": "", "fr": ""},
        {"kind": "cta", "badge": "BidEasy", "headline": "안전 투찰가", "body": "무료", "fl": "", "fr": ""},
    ],
    "reels_script": {"hook_3s": "훅", "points": ["p1"], "cta": "cta"},
    "youtube": {"script_md": "대본", "chapters": ["00:00 인트로"], "description": "설명"},
    "naver_summary_md": "요약",
}


class TestChannelAssets:
    """Phase 2 — 파생 하네스·발행 훅·주간 루프."""

    def _mk_engine_post(self, db, code="K1"):
        db.query(models.BlogPost).filter(models.BlogPost.slug == ce.slug_for(code)).delete()
        db.commit()
        post = models.BlogPost(
            slug=ce.slug_for(code), title="t", body_md="b", body_html="<p>b</p>",
            status="draft", source="auto", blocks_json=dict(SAMPLE_BLOCKS),
        )
        db.add(post); db.commit(); db.refresh(post)
        return post

    def test_ensure_assets_idempotent_and_fr_normalized(self, db_session, monkeypatch):
        post = self._mk_engine_post(db_session)
        monkeypatch.setattr(ce, "derive_channel_assets", lambda b: dict(SAMPLE_ASSETS))
        assert ce.ensure_channel_assets(db_session, post) is True
        db_session.refresh(post)
        assert post.channel_assets_json["reels_script"]["hook_3s"] == "훅"
        # 멱등 — 이미 있으면 재파생 안 함
        assert ce.ensure_channel_assets(db_session, post) is False

    def test_ensure_assets_no_llm_is_noop_not_error(self, db_session, monkeypatch):
        post = self._mk_engine_post(db_session, "K2")
        monkeypatch.setattr(ce.settings, "OPENAI_API_KEY", "")
        assert ce.ensure_channel_assets(db_session, post) is False  # 예외 없이 False
        db_session.refresh(post)
        assert post.channel_assets_json is None

    def test_next_unconsumed_topic_priority_order(self, db_session):
        db_session.query(models.BlogPost).filter(
            models.BlogPost.slug.in_([ce.slug_for(t["code"]) for t in ce.TOPIC_SEEDS])
        ).delete(synchronize_session=False)
        db_session.commit()
        t = ce.next_unconsumed_topic(db_session)
        assert t["code"] == "K1"  # P1 최우선·코드순
        # K1 소비 후엔 K2
        db_session.add(models.BlogPost(slug=ce.slug_for("K1"), title="t", body_md="b", body_html="h"))
        db_session.commit()
        assert ce.next_unconsumed_topic(db_session)["code"] == "K2"

    def test_admin_publish_triggers_derivation(self, admin_client, db_session, monkeypatch):
        post = self._mk_engine_post(db_session, "K3")
        monkeypatch.setattr(ce, "derive_channel_assets", lambda b: dict(SAMPLE_ASSETS))
        res = admin_client.post(f"/api/v1/admin/blog/{post.id}/publish")
        assert res.status_code == 200
        assert res.json()["status"] == "published"
        assert res.json()["channel_assets_json"]["instagram_cards"]

    def test_derive_endpoint_400_without_blocks(self, admin_client, db_session):
        db_session.query(models.BlogPost).filter(models.BlogPost.slug == "no-blocks-post").delete()
        db_session.commit()
        p = models.BlogPost(slug="no-blocks-post", title="t", body_md="b", body_html="h")
        db_session.add(p); db_session.commit(); db_session.refresh(p)
        assert admin_client.post(f"/api/v1/admin/blog/{p.id}/derive-assets").status_code == 400

    def test_derive_endpoint_503_without_llm(self, admin_client, db_session, monkeypatch):
        post = self._mk_engine_post(db_session, "K4")
        monkeypatch.setattr(ce.settings, "OPENAI_API_KEY", "")
        assert admin_client.post(f"/api/v1/admin/blog/{post.id}/derive-assets").status_code == 503


class TestQueueSustainability:
    """큐 소진이 조용히 지나가지 않는다 — 잔여 카운트·경보·AI 후보 제안."""

    def _clear_topic_posts(self, db):
        db.query(models.BlogPost).filter(
            models.BlogPost.slug.in_([ce.slug_for(t["code"]) for t in ce.TOPIC_SEEDS])
        ).delete(synchronize_session=False)
        db.commit()

    def test_remaining_topics_counts(self, db_session):
        self._clear_topic_posts(db_session)
        assert ce.remaining_topics(db_session) == 24
        db_session.add(models.BlogPost(slug=ce.slug_for("K1"), title="t", body_md="b", body_html="h"))
        db_session.commit()
        assert ce.remaining_topics(db_session) == 23

    def test_propose_returns_none_without_llm(self, monkeypatch):
        monkeypatch.setattr(ce.settings, "OPENAI_API_KEY", "")
        assert ce.propose_topic_candidates(5) is None

    def test_propose_endpoint_503_without_llm(self, admin_client, monkeypatch):
        monkeypatch.setattr(ce.settings, "OPENAI_API_KEY", "")
        res = admin_client.get("/api/v1/admin/blog/topics/propose")
        assert res.status_code == 503

    def test_propose_endpoint_success_with_mock(self, admin_client, monkeypatch):
        monkeypatch.setattr(
            ce, "propose_topic_candidates",
            lambda n=8: [{"title": "새 주제", "angle": "앵글", "keyword": "kw", "priority": "P2"}],
        )
        res = admin_client.get("/api/v1/admin/blog/topics/propose?n=3")
        assert res.status_code == 200
        data = res.json()
        assert data["candidates"][0]["title"] == "새 주제"
        assert "remaining" in data
        assert "자동 편입되지 않아요" in data["note"]

    def test_topics_endpoint_includes_remaining(self, admin_client):
        res = admin_client.get("/api/v1/admin/blog/topics")
        assert res.status_code == 200
        assert isinstance(res.json()["remaining"], int)


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
