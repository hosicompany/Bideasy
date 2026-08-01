"""자동 검수 게이트 테스트 (콘텐츠 엔진 Phase 1 — 그림자 모드).

핵심 불변식 2개:
  1. 판정은 정확해야 한다 (금칙어·환각수치·중복·구조·이미지 경로)
  2. **판정은 발행을 막지 않는다** — 그림자 모드. 이게 깨지면 Phase 1의 전제가 무너진다.
"""
from app.db import models
from app.services import content_review as cr


def _post(db, slug="rv-1", body="본문", title="제목", status="draft", **kw):
    p = models.BlogPost(
        slug=slug, title=title, summary="요약", body_md=body,
        body_html=f"<p>{body}</p>", reading_time=3, status=status,
        source="auto", date="", **kw,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _long_body(extra="", filler="가"):
    """구조 검사를 통과하는 최소 본문 (2,000자 + 섹션 3 + 내부링크).

    `filler` 를 달리하면 서로 **중복이 아닌** 본문이 된다 — 중복 검사와 무관한
    테스트에서 두 글을 만들 때 반드시 다른 filler 를 쓸 것.
    """
    section = filler * 700
    return (
        f"## 첫 번째\n\n{section}\n\n## 두 번째\n\n{section}\n\n## 세 번째\n\n{section}\n\n"
        f"{extra}\n\n[투찰가 계산기](/calculator)로 확인해보세요.\n"
    )


# ─── ① 금칙어 ─────────────────────────────────────────────────

class TestBannedTerms:
    def test_plain_violation_is_fail(self):
        r = cr.check_banned_terms("저희 서비스는 낙찰률을 높여드립니다")
        assert r["level"] == cr.FAIL
        assert r["hits"][0]["term"] == "낙찰률"

    def test_critique_context_is_allowed(self):
        """K9 같은 '예측 광고 비판' 글이 자기 자신에게 걸리면 안 된다."""
        r = cr.check_banned_terms("'낙찰가 예측'을 약속하는 광고는 믿으면 안 돼요")
        assert r["level"] == cr.PASS

    def test_clean_text_passes(self):
        r = cr.check_banned_terms("안전한 투찰가를 1원 단위로 계산해요")
        assert r["level"] == cr.PASS


# ─── ② 출처 없는 수치 ─────────────────────────────────────────

class TestUnsourcedNumbers:
    def test_invented_statistic_is_warned(self):
        r = cr.check_unsourced_numbers("작년 평균 낙찰 성공은 63% 수준이었어요")
        assert r["level"] == cr.WARN
        assert any("63" in h["value"] for h in r["hits"])

    def test_factsheet_numbers_are_allowed(self):
        r = cr.check_unsourced_numbers("예비가격 변동폭은 통상 2% 입니다")
        assert r["level"] == cr.PASS

    def test_benign_context_ignored(self):
        """'3분 안에', '5가지'는 통계 주장이 아니다 (오탐 방지)."""
        r = cr.check_unsourced_numbers("3분 안에 정리했고 5가지만 기억하세요")
        assert r["level"] == cr.PASS

    def test_decimal_rate_is_not_split_by_sentence_break(self):
        """★ 실측 회귀 — 문장 분리가 '89.745%' 를 '89' / '745%' 로 쪼개면 안 된다.

        발행된 상록수 4편이 전부 이 버그로 거짓 경보를 맞았다(하한율이 통째로
        '출처 없는 수치'로 잡힘).
        """
        r = cr.check_unsourced_numbers("이 공고의 낙찰하한율은 89.745% 입니다. 확인하세요.")
        assert r["level"] == cr.PASS, r["hits"]

    def test_lower_limit_whitelist_follows_single_source(self):
        """하한율 화이트리스트는 lower_limits.py 를 따라간다 (하드코딩 드리프트 방지)."""
        from app.services import lower_limits as ll
        for _, rate in ll._CONSTRUCTION_2026 + ll._CONSTRUCTION_OLD:
            r = cr.check_unsourced_numbers(f"하한율은 {rate}% 예요")
            assert r["level"] == cr.PASS, f"{rate} 가 오탐됨"

    def test_db_numbers_are_allowed(self):
        blocks = {"data_blocks": [{"numbers": [{"participants": 42}]}]}
        allowed = cr.allowed_numbers_from_blocks(blocks)
        r = cr.check_unsourced_numbers("가장 치열했던 공고는 42개사가 몰렸어요", allowed)
        assert r["level"] == cr.PASS


# ─── ③ 중복도 ─────────────────────────────────────────────────

class TestDuplication:
    def test_near_identical_is_fail(self, db_session):
        db_session.query(models.BlogPost).delete()
        db_session.commit()
        body = _long_body()
        _post(db_session, "dup-old", body=body, status="published")
        r = cr.check_duplication(db_session, body, exclude_slug="dup-new")
        assert r["level"] == cr.FAIL
        assert r["nearest"] == "dup-old"

    def test_distinct_content_passes(self, db_session):
        db_session.query(models.BlogPost).delete()
        db_session.commit()
        _post(db_session, "dup-a", body="가" * 800, status="published")
        r = cr.check_duplication(db_session, "완전히 다른 주제의 글" + "나" * 800)
        assert r["level"] == cr.PASS

    def test_excludes_self(self, db_session):
        db_session.query(models.BlogPost).delete()
        db_session.commit()
        body = _long_body()
        _post(db_session, "dup-self", body=body, status="published")
        r = cr.check_duplication(db_session, body, exclude_slug="dup-self")
        assert r["level"] == cr.PASS   # 자기 자신과 비교하지 않음


# ─── ④ 구조 ───────────────────────────────────────────────────

class TestStructure:
    def test_thin_body_warns(self):
        r = cr.check_structure("## 하나\n\n짧아요")
        assert r["level"] == cr.WARN
        assert any("미만" in i for i in r["issues"])

    def test_length_not_enforced_for_handwritten(self):
        """★ 실측 회귀 — 분량 기준은 LLM 글에만. 손글씨 상록수(1,000자대)가
        전부 WARN 을 맞던 문제."""
        short = "## 하나\n\n내용\n\n## 둘\n\n내용\n\n## 셋\n\n[계산기](/calculator)"
        assert cr.check_structure(short, enforce_length=False)["level"] == cr.PASS
        assert cr.check_structure(short, enforce_length=True)["level"] == cr.WARN

    def test_review_applies_length_only_to_auto_posts(self, db_session):
        db_session.query(models.BlogPost).delete()
        db_session.commit()
        short = "## 하나\n\n내용\n\n## 둘\n\n내용\n\n## 셋\n\n[계산기](/calculator)"
        manual = _post(db_session, "st-manual", body=short)
        manual.source = "admin"
        auto = _post(db_session, "st-auto", body=short + "\n\n다른 내용" * 5)
        auto.source = "auto"
        db_session.commit()
        assert cr.review_post(db_session, manual, use_llm=False)["verdict"] == cr.PASS
        assert cr.review_post(db_session, auto, use_llm=False)["verdict"] == cr.WARN

    def test_missing_internal_link_warns(self):
        body = "## 하나\n\n" + "가" * 2500 + "\n\n## 둘\n\n내용\n\n## 셋\n\n내용"
        r = cr.check_structure(body)
        assert "내부링크 없음 — 회수 경로 누락" in r["issues"]

    def test_good_structure_passes(self):
        assert cr.check_structure(_long_body())["level"] == cr.PASS

    def test_commented_images_do_not_count_as_body(self):
        """주석 처리된 이미지 자리는 분량으로 세지 않는다."""
        body = "<!-- " + "가" * 3000 + " -->\n\n## 하나\n\n짧아요"
        assert cr.check_structure(body)["level"] == cr.WARN


# ─── ⑤ 이미지 참조 ────────────────────────────────────────────

class TestImageRefs:
    def test_commented_placeholder_is_not_live(self):
        body = "<!-- 이미지 자리\n![캡션](/assets/blog/knowledge-k1/hero.png)\n-->"
        r = cr.check_image_refs(body, "knowledge-k1")
        assert r["level"] == cr.PASS and r["live"] == []

    def test_wrong_slug_is_warned(self):
        body = "![캡션](/assets/blog/other-post/hero.png)"
        r = cr.check_image_refs(body, "knowledge-k1")
        assert r["level"] == cr.WARN
        assert "다른 글 자산" in r["issues"][0]

    def test_correct_live_image_passes(self):
        body = "![캡션](/assets/blog/knowledge-k1/hero.png)"
        r = cr.check_image_refs(body, "knowledge-k1")
        assert r["level"] == cr.PASS and len(r["live"]) == 1


# ─── ⑥ LLM 심판 ───────────────────────────────────────────────

class TestLlmJudge:
    def test_skipped_without_key(self, monkeypatch):
        from app.services import content_llm
        monkeypatch.setattr(content_llm.settings, "CONTENT_LLM_API_KEY", "")
        monkeypatch.setattr(content_llm.settings, "OPENAI_API_KEY", "")
        r = cr.check_llm_judge("제목", "본문")
        assert r["level"] == cr.PASS and r["skipped"] is True

    def test_high_severity_is_fail(self, monkeypatch):
        monkeypatch.setattr(cr.content_llm, "available", lambda: True)
        monkeypatch.setattr(cr.content_llm, "chat_json", lambda *a, **k: {
            "issues": [{"severity": "high", "quote": "무조건 낙찰됩니다", "why": "보장 표현"}]
        })
        assert cr.check_llm_judge("t", "b")["level"] == cr.FAIL

    def test_medium_is_warn_and_none_is_pass(self, monkeypatch):
        monkeypatch.setattr(cr.content_llm, "available", lambda: True)
        monkeypatch.setattr(cr.content_llm, "chat_json", lambda *a, **k: {
            "issues": [{"severity": "medium", "quote": "q", "why": "w"}]})
        assert cr.check_llm_judge("t", "b")["level"] == cr.WARN
        monkeypatch.setattr(cr.content_llm, "chat_json", lambda *a, **k: {"issues": []})
        assert cr.check_llm_judge("t", "b")["level"] == cr.PASS

    def test_judge_failure_warns_not_crashes(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("provider down")
        monkeypatch.setattr(cr.content_llm, "available", lambda: True)
        monkeypatch.setattr(cr.content_llm, "chat_json", boom)
        r = cr.check_llm_judge("t", "b")
        assert r["level"] == cr.WARN and r["skipped"] is True


# ─── 통합 + 그림자 모드 불변식 ────────────────────────────────

class TestReviewIntegration:
    def test_verdict_is_worst_check(self, db_session):
        db_session.query(models.BlogPost).delete()
        db_session.commit()
        p = _post(db_session, "rv-bad", body=_long_body("낙찰률이 높아집니다"))
        r = cr.review_post(db_session, p, use_llm=False)
        assert r["verdict"] == cr.FAIL
        assert "banned_terms" in r["blocking"]

    def test_clean_post_passes(self, db_session):
        db_session.query(models.BlogPost).delete()
        db_session.commit()
        p = _post(db_session, "rv-good", body=_long_body())
        r = cr.review_post(db_session, p, use_llm=False)
        assert r["verdict"] == cr.PASS and r["blocking"] == []

    def test_review_is_stored(self, db_session):
        db_session.query(models.BlogPost).delete()
        db_session.commit()
        p = _post(db_session, "rv-store", body=_long_body())
        cr.review_and_store(db_session, p, use_llm=False)
        db_session.refresh(p)
        assert p.review_json["verdict"] == cr.PASS
        assert p.review_json["mode"] == "shadow"

    def test_shadow_mode_does_not_block_publish(self, admin_client, db_session):
        """★ Phase 1 전제 — FAIL 판정이어도 발행은 종전대로 된다."""
        db_session.query(models.BlogPost).delete()
        db_session.commit()
        p = _post(db_session, "rv-shadow", body=_long_body("낙찰률 보장"))
        cr.review_and_store(db_session, p, use_llm=False)
        db_session.refresh(p)
        assert p.review_json["verdict"] == cr.FAIL

        r = admin_client.post(f"/api/v1/admin/blog/{p.id}/publish")
        assert r.status_code == 200
        assert r.json()["status"] == "published"

    def test_review_failure_does_not_raise(self, db_session, monkeypatch):
        """검수가 깨져도 초안 생성·발행 흐름은 살아 있어야 한다."""
        p = _post(db_session, "rv-boom", body=_long_body())
        monkeypatch.setattr(cr, "review_post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert cr.review_and_store(db_session, p) is None


class TestReviewEndpoints:
    def test_rerun_endpoint(self, admin_client, db_session):
        db_session.query(models.BlogPost).delete()
        db_session.commit()
        p = _post(db_session, "rv-api", body=_long_body())
        r = admin_client.post(f"/api/v1/admin/blog/{p.id}/review")
        assert r.status_code == 200
        assert r.json()["review_json"]["verdict"] in (cr.PASS, cr.WARN, cr.FAIL)

    def test_stats_crosstab(self, admin_client, db_session):
        db_session.query(models.BlogPost).delete()
        db_session.commit()
        # filler 를 달리해 서로 중복이 아니게 (중복 검사가 판정을 오염시키지 않도록)
        a = _post(db_session, "rv-s1", body=_long_body(filler="가"), status="published")
        b = _post(db_session, "rv-s2", body=_long_body("낙찰률", filler="나"), status="published")
        _post(db_session, "rv-s3", body=_long_body(filler="다"))          # 미검수
        cr.review_and_store(db_session, a, use_llm=False)
        cr.review_and_store(db_session, b, use_llm=False)

        d = admin_client.get("/api/v1/admin/blog/review-stats").json()
        assert d["mode"] == "shadow"
        assert d["matrix"]["PASS"]["published"] == 1
        assert d["matrix"]["FAIL"]["published"] == 1
        assert d["false_alarms"] == 1        # FAIL 인데 발행됨 = 거짓 경보 후보
        assert d["unreviewed"] == 1

    def test_stats_requires_admin(self, client):
        assert client.get("/api/v1/admin/blog/review-stats").status_code in (401, 403)

    def test_route_not_shadowed_by_post_id(self, admin_client):
        """'review-stats' 가 /blog/{post_id}(int) 에 잡혀 422 가 되면 안 된다."""
        assert admin_client.get("/api/v1/admin/blog/review-stats").status_code == 200
