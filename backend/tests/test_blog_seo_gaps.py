"""블로그 SEO·정합성 갭 수정 회귀 테스트 (2026-08-01 코드리뷰 후속).

리뷰에서 확인된 '문서에는 있는데 코드에 없던' 4건:
  ① 얇은 주 데이터스토리 자동발행 방어 (CONTENT_ENGINE §9.2)
  ② 입찰상식 Q&A → FAQPage 구조화 데이터 (§9.3)
  ③ 엔진 글 hero 미설정 → og:image 누락
  ⑤ 콘텐츠 LLM 키 게이트 불일치 (CONTENT_LLM_API_KEY 단독 구성에서 반쪽 동작)
"""
import json
import re
from datetime import date, datetime, timedelta

import pytest

from app.db import models
from app.services import content_engine as ce
from app.services import content_llm
from app.services import data_story


# ─── 공통 헬퍼 ────────────────────────────────────────────────

def _seed_week(db, ref: date, n: int):
    """ref 기준 지난주에 개찰결과 n건 시딩. 반환: 그 주 monday."""
    mon, _ = data_story.last_completed_week(ref)
    base = datetime(mon.year, mon.month, mon.day) + timedelta(days=1, hours=10)
    for i in range(n):
        db.add(models.OpeningResult(
            bid_no=f"SEO-{mon.isoformat()}-{i}", organization="기관", region="서울",
            open_date=base, basic_price=1_000_000_000, winner_rate=88.0,
            participants_count=(i % 9) + 1,
        ))
    db.commit()
    return mon


def _clean(db):
    db.query(models.OpeningResult).delete()
    db.query(models.BlogPost).delete()
    db.commit()


# ─── ① 얇은 주 게이트 ─────────────────────────────────────────

class TestThinWeekGate:
    def test_below_threshold_is_skipped(self, db_session, monkeypatch):
        """임계 미만이면 초안을 아예 만들지 않는다 (doorway/중복 방어)."""
        _clean(db_session)
        monkeypatch.setattr(data_story.settings, "BLOG_MIN_WEEKLY_RECORDS", 10)
        _seed_week(db_session, date(2025, 9, 15), n=3)
        post, status = data_story.create_weekly_draft(db_session, ref_date=date(2025, 9, 15))
        assert status == "thin_data"
        assert post is None
        assert db_session.query(models.BlogPost).count() == 0

    def test_at_threshold_is_created(self, db_session, monkeypatch):
        _clean(db_session)
        monkeypatch.setattr(data_story.settings, "BLOG_MIN_WEEKLY_RECORDS", 3)
        _seed_week(db_session, date(2025, 9, 22), n=3)
        post, status = data_story.create_weekly_draft(db_session, ref_date=date(2025, 9, 22))
        assert status == "created" and post is not None

    def test_allow_thin_overrides(self, db_session, monkeypatch):
        """사람이 판단해 강행할 때만 통과 (자동 경로는 못 씀)."""
        _clean(db_session)
        monkeypatch.setattr(data_story.settings, "BLOG_MIN_WEEKLY_RECORDS", 10)
        _seed_week(db_session, date(2025, 9, 29), n=2)
        post, status = data_story.create_weekly_draft(
            db_session, ref_date=date(2025, 9, 29), allow_thin=True
        )
        assert status == "created" and post is not None

    def test_threshold_zero_disables_gate(self, db_session, monkeypatch):
        """킬스위치 — 0 이면 기존 동작(데이터 1건도 발행)."""
        _clean(db_session)
        monkeypatch.setattr(data_story.settings, "BLOG_MIN_WEEKLY_RECORDS", 0)
        _seed_week(db_session, date(2025, 10, 6), n=1)
        _, status = data_story.create_weekly_draft(db_session, ref_date=date(2025, 10, 6))
        assert status == "created"

    def test_empty_week_still_no_data_not_thin(self, db_session, monkeypatch):
        """데이터 0건은 기존 no_data 를 유지 (상태 구분 보존)."""
        _clean(db_session)
        monkeypatch.setattr(data_story.settings, "BLOG_MIN_WEEKLY_RECORDS", 10)
        post, status = data_story.create_weekly_draft(db_session, ref_date=date(2025, 10, 13))
        assert status == "no_data" and post is None

    def test_admin_endpoint_409_and_force(self, admin_client, db_session, monkeypatch):
        _clean(db_session)
        monkeypatch.setattr(data_story.settings, "BLOG_MIN_WEEKLY_RECORDS", 50)
        _seed_week(db_session, date.today(), n=2)

        r = admin_client.post("/api/v1/admin/blog/generate-data-story")
        assert r.status_code == 409
        assert "임계" in r.json()["detail"]

        r2 = admin_client.post("/api/v1/admin/blog/generate-data-story?force=true")
        assert r2.status_code == 200

    def test_celery_task_reports_thin_skip(self, db_session, monkeypatch):
        """조용한 스킵 금지 — task 가 thin_data 를 보고한다."""
        from app.tasks import content_tasks

        _clean(db_session)
        monkeypatch.setattr(data_story.settings, "BLOG_MIN_WEEKLY_RECORDS", 50)
        _seed_week(db_session, date.today(), n=2)
        monkeypatch.setattr(content_tasks, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(db_session, "close", lambda: None)

        out = content_tasks.generate_weekly_data_story()
        assert out == {"ok": True, "skipped": "thin_data"}


# ─── ② FAQPage 구조화 데이터 ──────────────────────────────────

def _mk_engine_post(db, slug, faq, **kw):
    post = models.BlogPost(
        slug=slug, title="테스트 글", summary="요약", category="입찰상식",
        body_md="본문", body_html="<p>본문</p>", reading_time=3,
        status="published", source="auto", date="2026-07-20",
        blocks_json={"track": "knowledge", "hook": "훅", "faq": faq}, **kw,
    )
    db.add(post)
    db.commit()
    return post


def _faq_jsonld(html: str):
    """페이지의 ld+json 블록 중 FAQPage 를 파싱해 반환 (없으면 None)."""
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        data = json.loads(m.group(1))          # 파싱 실패 = 깨진 JSON-LD → 테스트 실패
        if data.get("@type") == "FAQPage":
            return data
    return None


class TestFaqPageSchema:
    def test_faq_blocks_emit_faqpage(self, client, db_session):
        _mk_engine_post(db_session, "seo-faq-1", [
            {"q": "사정률은 미리 알 수 있나요?", "a": "아니요, 개찰 전까지 비공개예요."},
            {"q": "A값은 왜 따로 계산하나요?", "a": "사후정산 비목이라 투찰률이 안 붙어요."},
        ])
        r = client.get("/blog/seo-faq-1")
        assert r.status_code == 200
        data = _faq_jsonld(r.text)
        assert data is not None
        assert len(data["mainEntity"]) == 2
        assert data["mainEntity"][0]["name"] == "사정률은 미리 알 수 있나요?"
        assert data["mainEntity"][0]["acceptedAnswer"]["text"].startswith("아니요")

    def test_post_without_faq_has_no_faqpage(self, client, db_session):
        _mk_engine_post(db_session, "seo-faq-none", [])
        r = client.get("/blog/seo-faq-none")
        assert r.status_code == 200
        assert _faq_jsonld(r.text) is None
        assert '"@type": "Article"' in r.text        # Article 은 그대로 유지

    def test_file_post_unaffected(self, client):
        """파일 글(상록수)은 blocks 가 없어 FAQPage 를 내지 않는다."""
        r = client.get("/blog/a-value-guide")
        assert r.status_code == 200
        assert _faq_jsonld(r.text) is None

    def test_malformed_faq_entries_do_not_break_json(self, client, db_session):
        """q·a 가 빠진 항목이 섞여도 JSON-LD 가 깨지지 않는다 (콤마 누수 방지)."""
        _mk_engine_post(db_session, "seo-faq-bad", [
            {"q": "정상 질문", "a": "정상 답변"},
            {"q": "답 없는 질문"},
            {"a": "질문 없는 답"},
        ])
        r = client.get("/blog/seo-faq-bad")
        data = _faq_jsonld(r.text)                   # 파싱 자체가 검증
        assert data is not None
        assert len(data["mainEntity"]) == 1

    def test_faq_quotes_are_escaped(self, client, db_session):
        """따옴표가 든 질문도 유효한 JSON 으로 나간다."""
        _mk_engine_post(db_session, "seo-faq-quote", [
            {"q": '"예측" 광고를 믿어도 되나요?', "a": '아니요 — "적중률"은 검증 불가예요.'},
        ])
        r = client.get("/blog/seo-faq-quote")
        data = _faq_jsonld(r.text)
        assert data["mainEntity"][0]["name"] == '"예측" 광고를 믿어도 되나요?'


# ─── ③ 엔진 글 hero → og:image ────────────────────────────────

class TestEngineHero:
    def test_hero_path_from_image_prompts(self):
        blocks = {"image_prompts": [{"slot": "hero", "caption": "표지", "prompt": "..."}]}
        assert ce.hero_path_for(blocks, "knowledge-k1") == "/assets/blog/knowledge-k1/hero.png"

    def test_no_hero_prompt_means_empty(self):
        blocks = {"image_prompts": [{"slot": "diagram", "caption": "도식", "prompt": "..."}]}
        assert ce.hero_path_for(blocks, "knowledge-k1") == ""
        assert ce.hero_path_for({}, "knowledge-k1") == ""

    def test_draft_sets_hero(self, db_session, monkeypatch):
        blocks = {
            "hook": "훅", "summary_30s": "요약", "seo_summary": "메타",
            "key_points": [{"heading": "H", "body": "B"}],
            "image_prompts": [{"slot": "hero", "caption": "표지", "prompt": "p"}],
        }
        monkeypatch.setattr(ce, "generate_blocks", lambda t: dict(blocks))
        db_session.query(models.BlogPost).filter(
            models.BlogPost.slug == ce.slug_for("K3")).delete()
        db_session.commit()
        post, status = ce.create_draft_from_topic(db_session, "K3")
        assert status == "created"
        assert post.hero == "/assets/blog/knowledge-k3/hero.png"

    def test_engine_post_renders_og_image(self, client, db_session):
        db_session.add(models.BlogPost(
            slug="seo-hero-1", title="히어로 글", summary="요약",
            hero="/assets/blog/seo-hero-1/hero.png",
            body_md="본문", body_html="<p>본문</p>", reading_time=2,
            status="published", source="auto", date="2026-07-21",
        ))
        db_session.commit()
        r = client.get("/blog/seo-hero-1")
        assert 'property="og:image"' in r.text
        assert 'name="twitter:image"' in r.text
        assert "/assets/blog/seo-hero-1/hero.png" in r.text


# ─── ⑤ 콘텐츠 LLM 키 게이트 ───────────────────────────────────

class TestContentLlmGate:
    def test_dedicated_key_alone_counts_as_available(self, monkeypatch):
        """OpenRouter 전용 구성(OPENAI_API_KEY 없음)에서도 콘텐츠 기능이 살아있어야 한다."""
        monkeypatch.setattr(content_llm.settings, "OPENAI_API_KEY", "")
        monkeypatch.setattr(content_llm.settings, "CONTENT_LLM_API_KEY", "sk-or-test")
        assert content_llm.available() is True
        assert content_llm.primary_key() == "sk-or-test"

    def test_openai_key_alone_still_works(self, monkeypatch):
        monkeypatch.setattr(content_llm.settings, "CONTENT_LLM_API_KEY", "")
        monkeypatch.setattr(content_llm.settings, "OPENAI_API_KEY", "sk-openai")
        assert content_llm.available() is True
        assert content_llm.primary_key() == "sk-openai"

    def test_no_keys_means_unavailable(self, monkeypatch):
        monkeypatch.setattr(content_llm.settings, "CONTENT_LLM_API_KEY", "")
        monkeypatch.setattr(content_llm.settings, "OPENAI_API_KEY", "")
        assert content_llm.available() is False
        with pytest.raises(RuntimeError):
            content_llm.chat_json("sys", "user")

    @pytest.mark.parametrize("fn", [
        lambda: ce.derive_channel_assets({"hook": "훅"}),
        lambda: ce.propose_topic_candidates(3),
        lambda: ce.generate_blocks({"code": "K1", "title": "t", "angle": "a", "keyword": "k"}),
        lambda: data_story._llm_narrative("ctx"),
    ])
    def test_all_content_calls_share_one_gate(self, monkeypatch, fn):
        """네 호출부가 **같은** 게이트를 쓴다 — 하나만 조용히 죽는 일이 없도록."""
        monkeypatch.setattr(content_llm.settings, "CONTENT_LLM_API_KEY", "")
        monkeypatch.setattr(content_llm.settings, "OPENAI_API_KEY", "")
        assert fn() is None

    def test_cheap_model_used_for_light_calls(self, monkeypatch):
        """정본 외 호출은 저가 모델로 — 리팩터링이 비용을 올리지 않았는지 고정."""
        monkeypatch.setattr(content_llm.settings, "CONTENT_LLM_CHEAP_MODEL", "gpt-4o-mini")
        monkeypatch.setattr(content_llm.settings, "CONTENT_LLM_MODEL", "gpt-4o")
        seen = {}

        def fake(system, user, *, max_tokens=2000, temperature=0.4, model=None):
            seen["model"] = model
            return {"instagram_cards": [{"kind": "cover"}]}

        monkeypatch.setattr(content_llm, "chat_json", fake)
        monkeypatch.setattr(content_llm.settings, "OPENAI_API_KEY", "sk-x")
        ce.derive_channel_assets({"hook": "훅"})
        assert seen["model"] == "gpt-4o-mini"
