"""모의투찰 Phase 1 — 등록·채점 테스트.

설계 정본: docs/MOCK_BIDDING_DESIGN.md
여기서 지키는 것은 §0.5 유효성 체크 4가지와 §3 등록 대상 규칙이다.
"""
from datetime import datetime, timedelta

import pytest

from app.db import models
from app.services import mock_bidding as mb


def _notice(bid_no="MB-1", *, basic_price=100_000_000, bid_method="적격심사제",
            contract_type="CONSTRUCTION", notice_kind="등록공고",
            end_offset_h=1, llr=89.745, a_value=0, prdprc=(15, 4),
            re_notice="N"):
    return models.Notice(
        bid_no=bid_no, title="테스트 공고", basic_price=basic_price,
        contract_type=contract_type, bid_method=bid_method,
        notice_kind=notice_kind, lower_limit_rate=llr, a_value=a_value,
        # Notice.end_date 는 opengDt(KST 표기) 축이므로 픽스처도 KST 로 만든다
        end_date=mb.now_kst() + timedelta(hours=end_offset_h),
        prdprc_total=prdprc[0], prdprc_draw=prdprc[1], re_notice_yn=re_notice,
    )


def _opening(bid_no="MB-1", *, basic=100_000_000, reserved=100_000_000,
             winner=90_000_000):
    return models.OpeningResult(
        bid_no=bid_no, basic_price=basic, reserved_price=reserved,
        winner_price=winner, winner_rate=winner / basic * 100,
        open_date=mb.now_kst(),
    )


# ── 시간대 (배포 직후 실제로 터진 버그) ────────────────────────

class TestTimezone:
    """`Notice.end_date` 는 opengDt(KST 표기)를 naive 로 저장한 값인데
    운영 컨테이너 TZ 는 UTC 다. `datetime.now()` 로 비교하면 9시간 어긋나
    등록 후보가 0건이 되고, 더 나쁘게는 마감이 지난 공고를 등록하게 된다.
    """

    def test_now_kst_is_utc_plus_9(self):
        """로컬(KST)에서든 CI(UTC)에서든 항상 성립해야 하는 회귀 가드."""
        from datetime import timezone

        utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        diff_h = (mb.now_kst() - utc_naive).total_seconds() / 3600
        assert 8.9 < diff_h < 9.1

    def test_register_uses_kst_not_local_clock(self, db_session):
        """KST 기준 1시간 뒤 마감 공고가 후보로 잡혀야 한다.

        컨테이너가 UTC 인 CI 에서 실제 검증력을 갖는다 — now_kst 가 없으면
        9시간 어긋나 이 공고를 놓친다.
        """
        n = _notice("MB-TZ-1")
        n.end_date = mb.now_kst() + timedelta(hours=1)
        db_session.add(n)
        db_session.commit()

        r = mb.register_due_notices(db_session, window_hours=2)
        assert r["registered"] == 5

    def test_deadline_check_uses_kst(self, db_session):
        """KST 기준 이미 지난 마감은 등록되지 않아야 한다."""
        n = _notice("MB-TZ-2")
        n.end_date = mb.now_kst() - timedelta(minutes=30)
        db_session.add(n)
        db_session.commit()

        r = mb.register_notice(db_session, n)
        assert r["skipped"] == "deadline_passed"


# ── §3 등록 대상 규칙 ─────────────────────────────────────────

class TestEligibility:
    def test_construction_qualifies(self):
        assert mb.is_eligible(_notice())[0] is True

    def test_cancelled_notice_excluded(self):
        """취소공고는 실측 5.6% 존재 — 투찰할 수 없는 공고다."""
        ok, reason = mb.is_eligible(_notice(notice_kind="취소공고"))
        assert ok is False and reason == "cancelled_notice"

    def test_non_price_competition_excluded(self):
        ok, reason = mb.is_eligible(_notice(bid_method="협상에의한계약"))
        assert ok is False and reason == "bid_method_not_eligible"

    def test_service_excluded(self):
        ok, reason = mb.is_eligible(_notice(contract_type="SERVICE"))
        assert ok is False and reason == "not_construction"

    def test_no_basis_amount_excluded(self):
        """금액 기준을 못 구하면 등록하지 않는다.

        시행 전(BASIS_AMOUNT_ENFORCE=False)에는 basic_price 가 그 역할을 하고,
        시행 후에는 basis_amount 가 없으면 같은 사유로 제외된다.
        """
        ok, reason = mb.is_eligible(_notice(basic_price=0))
        assert ok is False and reason == "no_basis_amount"


# ── §0.3 arm 구성 ─────────────────────────────────────────────

class TestArmPrices:
    def test_all_five_arms(self):
        arms = {a.arm for a in mb.compute_arm_prices(_notice())}
        assert arms == set(mb.ARMS)

    def test_standard_is_975_of_basic(self):
        prices = {a.arm: a.price for a in mb.compute_arm_prices(_notice(basic_price=100_000_000))}
        assert prices["standard"] == 97_500_000

    def test_aggressive_is_88_of_basic(self):
        prices = {a.arm: a.price for a in mb.compute_arm_prices(_notice(basic_price=100_000_000))}
        assert prices["aggressive"] == 88_000_000

    def test_arms_differ(self):
        """전부 같은 값이면 arm 을 나눈 의미가 없다."""
        prices = {a.arm: a.price for a in mb.compute_arm_prices(_notice())}
        assert len(set(prices.values())) >= 3

    def test_zero_basic_price_yields_nothing(self):
        assert mb.compute_arm_prices(_notice(basic_price=0)) == []


# ── 하한율 소스 ───────────────────────────────────────────────

class TestLowerLimitSource:
    def test_notice_value_preferred(self):
        rate, src = mb.resolve_lower_limit_rate(_notice(llr=89.745))
        assert rate == 89.745 and src == "notice"

    def test_table_fallback_when_missing(self):
        rate, src = mb.resolve_lower_limit_rate(_notice(llr=None))
        assert src == "table" and rate > 0


# ── §0.5 유효성 체크 ──────────────────────────────────────────

class TestRegistration:
    def test_registers_five_arms(self, db_session):
        n = _notice("MB-REG-1")
        db_session.add(n)
        db_session.commit()

        r = mb.register_notice(db_session, n)
        db_session.commit()

        assert r["registered"] == 5
        rows = db_session.query(models.MockBid).filter_by(bid_no="MB-REG-1").all()
        assert {x.arm for x in rows} == set(mb.ARMS)

    def test_rejects_after_deadline(self, db_session):
        """§0.5-1 — 마감 후 등록은 거부. 이 가드가 실험의 신뢰 근거다."""
        n = _notice("MB-LATE-1", end_offset_h=-1)   # 이미 마감
        db_session.add(n)
        db_session.commit()

        r = mb.register_notice(db_session, n)
        assert r["registered"] == 0 and r["skipped"] == "deadline_passed"
        assert db_session.query(models.MockBid).filter_by(bid_no="MB-LATE-1").count() == 0

    def test_registered_before_deadline(self, db_session):
        n = _notice("MB-REG-2")
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()

        for row in db_session.query(models.MockBid).filter_by(bid_no="MB-REG-2").all():
            assert row.registered_at < row.deadline_at

    def test_idempotent(self, db_session):
        """§0.5-2 — 재실행이 중복 등록을 만들지 않는다."""
        n = _notice("MB-IDEM-1")
        db_session.add(n)
        db_session.commit()

        mb.register_notice(db_session, n)
        db_session.commit()
        second = mb.register_notice(db_session, n)
        db_session.commit()

        assert second["registered"] == 0
        assert db_session.query(models.MockBid).filter_by(bid_no="MB-IDEM-1").count() == 5

    def test_snapshot_captured(self, db_session):
        """§P1 — 그때 우리가 본 정보를 박아 둔다."""
        n = _notice("MB-SNAP-1", basic_price=250_000_000, llr=89.745, a_value=7_000_000)
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()

        row = db_session.query(models.MockBid).filter_by(bid_no="MB-SNAP-1", arm="active").first()
        assert row.snapshot_basic_price == 250_000_000
        assert row.snapshot_a_value == 7_000_000
        assert row.a_value_source == "tier2"
        assert row.snapshot_lower_limit_rate == 89.745
        assert row.llr_source == "notice"
        assert row.snapshot_bid_method == "적격심사제"

    def test_cancelled_not_registered(self, db_session):
        n = _notice("MB-CANCEL-1", notice_kind="취소공고")
        db_session.add(n)
        db_session.commit()
        r = mb.register_notice(db_session, n)
        assert r["registered"] == 0
        assert db_session.query(models.MockBid).filter_by(bid_no="MB-CANCEL-1").count() == 0

    def test_large_notice_price_fits(self, db_session):
        """공사 기초금액은 실측 최대 6,203억 — int4(21.4억)로는 등록이 죽는다."""
        n = _notice("MB-BIG-1", basic_price=620_348_000_000)
        db_session.add(n)
        db_session.commit()

        r = mb.register_notice(db_session, n)
        db_session.commit()

        assert r["registered"] == 5
        row = db_session.query(models.MockBid).filter_by(bid_no="MB-BIG-1", arm="standard").first()
        assert row.price > 2_147_483_647          # int4 상한 초과값이 저장돼야 한다

    def test_bigint_column_types(self):
        """모델 타입 자체를 고정 — SQLite 는 정수 크기 제한이 없어 저장만으로는
        Postgres 회귀를 못 잡는다."""
        from sqlalchemy import BigInteger

        assert isinstance(models.MockBid.__table__.c.price.type, BigInteger)
        assert isinstance(models.MockBid.__table__.c.snapshot_a_value.type, BigInteger)

    def test_one_bad_notice_does_not_rollback_others(self, db_session, monkeypatch):
        """배치 중 1건이 커밋에서 실패해도 나머지 등록분은 살아남아야 한다.

        마지막에 한 번만 커밋하면 그 회차 전체가 날아가고, 마감이 지나 버려
        사전 등록은 재시도조차 못 한다.
        """
        good = _notice("MB-BATCH-OK")
        bad = _notice("MB-BATCH-BAD")
        db_session.add_all([good, bad])
        db_session.commit()

        real = mb.register_notice

        def flaky(db, notice, now=None):
            if notice.bid_no == "MB-BATCH-BAD":
                raise RuntimeError("simulated commit failure")
            return real(db, notice, now=now)

        monkeypatch.setattr(mb, "register_notice", flaky)
        r = mb.register_due_notices(db_session, window_hours=2)

        assert r["skips"].get("error") == 1
        assert db_session.query(models.MockBid).filter_by(bid_no="MB-BATCH-OK").count() == 5

    def test_batch_picks_due_only(self, db_session):
        """마감 임박(2h 이내)만 등록 — 먼 공고는 아직 건드리지 않는다."""
        db_session.add(_notice("MB-DUE-1", end_offset_h=1))
        db_session.add(_notice("MB-FAR-1", end_offset_h=48))
        db_session.commit()

        mb.register_due_notices(db_session, window_hours=2)

        assert db_session.query(models.MockBid).filter_by(bid_no="MB-DUE-1").count() == 5
        assert db_session.query(models.MockBid).filter_by(bid_no="MB-FAR-1").count() == 0


# ── 판정 (§0.2) ───────────────────────────────────────────────

class TestJudge:
    def test_win_inside_window(self):
        assert mb.judge(90, 88, 92) == "WIN"

    def test_dropout_below_limit(self):
        assert mb.judge(87, 88, 92) == "DROPOUT"

    def test_lost_above_winner(self):
        assert mb.judge(95, 88, 92) == "LOST"

    def test_boundary_at_limit_is_valid(self):
        """하한선 '이상'이 유효 — simulate_params 와 같은 부등호."""
        assert mb.judge(88, 88, 92) == "WIN"

    def test_boundary_at_winner_is_win(self):
        assert mb.judge(92, 88, 92) == "WIN"

    def test_matches_simulate_params_definition(self):
        """optimizer.simulate_params 와 판정이 갈라지면 안 된다(§P3)."""
        import math
        from app.services.autocalibrate.optimizer import simulate_params
        from app.services.autocalibrate.dataset import BidRecord

        rec = BidRecord(
            bid_no="X", title="", org="", bid_method="적격심사제",
            basic_price=100_000_000, estimated_price=100_000_000,
            reserved_price=99_000_000, winner_price=89_500_000,
            winner_rate=89.5, lower_limit_rate=87.745, year=2025,
        )
        adj, margin = -0.5, 1.0
        sim = simulate_params([rec], adj, margin)

        predicted = rec.basic_price * (1 + adj / 100.0)
        target = math.floor(predicted * (rec.lower_limit_rate + margin) / 100.0 / 10) * 10
        limit = rec.reserved_price * rec.lower_limit_rate / 100.0
        ours = mb.judge(target, limit, rec.winner_price)

        assert (ours == "WIN") == (sim["win_rate"] == 100.0)
        assert (ours == "DROPOUT") == (sim["dropout_rate"] == 100.0)


# ── 채점 ──────────────────────────────────────────────────────

class TestScoring:
    def _prepare(self, db_session, bid_no, *, winner, reserved=100_000_000):
        n = _notice(bid_no)
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()
        db_session.add(_opening(bid_no, reserved=reserved, winner=winner))
        db_session.commit()
        # 마감 지난 것으로 만들어 채점 대상에 넣는다
        for row in db_session.query(models.MockBid).filter_by(bid_no=bid_no).all():
            row.deadline_at = mb.now_kst() - timedelta(hours=1)
        db_session.commit()

    def test_scores_all_arms(self, db_session):
        self._prepare(db_session, "MB-SC-1", winner=95_000_000)
        r = mb.score_pending(db_session)
        assert r["scored"] == 5
        assert sum(r["outcomes"].values()) == 5

    def test_standard_loses_when_winner_low(self, db_session):
        """기본값(97.5%)은 낙찰가보다 높아 LOST — 벤치마크 발견 1과 같은 구조."""
        self._prepare(db_session, "MB-SC-2", winner=90_000_000)
        mb.score_pending(db_session)

        row = (db_session.query(models.MockBidResult)
               .join(models.MockBid)
               .filter(models.MockBid.bid_no == "MB-SC-2",
                       models.MockBid.arm == "standard").first())
        assert row.outcome == "LOST"

    def test_aggressive_dropout_when_below_limit(self, db_session):
        """공격 투찰(88%)은 하한선(89.745%) 미만이라 무효."""
        self._prepare(db_session, "MB-SC-3", winner=95_000_000)
        mb.score_pending(db_session)

        row = (db_session.query(models.MockBidResult)
               .join(models.MockBid)
               .filter(models.MockBid.bid_no == "MB-SC-3",
                       models.MockBid.arm == "aggressive").first())
        assert row.outcome == "DROPOUT"

    def test_no_result_when_opening_missing(self, db_session):
        n = _notice("MB-SC-4")
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()
        for row in db_session.query(models.MockBid).filter_by(bid_no="MB-SC-4").all():
            row.deadline_at = mb.now_kst() - timedelta(hours=1)
        db_session.commit()

        r = mb.score_pending(db_session)
        assert r["outcomes"].get("NO_RESULT") == 5

    def test_no_result_not_duplicated(self, db_session):
        """개찰이 계속 안 붙어도 매 실행마다 행을 쌓지 않는다."""
        n = _notice("MB-SC-5")
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()
        for row in db_session.query(models.MockBid).filter_by(bid_no="MB-SC-5").all():
            row.deadline_at = mb.now_kst() - timedelta(hours=1)
        db_session.commit()

        mb.score_pending(db_session)
        mb.score_pending(db_session)

        cnt = (db_session.query(models.MockBidResult)
               .join(models.MockBid)
               .filter(models.MockBid.bid_no == "MB-SC-5").count())
        assert cnt == 5

    def test_registration_row_is_immutable(self, db_session):
        """§0.5-3 — 채점이 등록 내용을 바꾸면 안 된다(상태 플래그만 허용)."""
        self._prepare(db_session, "MB-IMMU-1", winner=95_000_000)
        before = {
            r.arm: (r.price, r.snapshot_basic_price, r.snapshot_lower_limit_rate)
            for r in db_session.query(models.MockBid).filter_by(bid_no="MB-IMMU-1").all()
        }
        mb.score_pending(db_session)
        after = {
            r.arm: (r.price, r.snapshot_basic_price, r.snapshot_lower_limit_rate)
            for r in db_session.query(models.MockBid).filter_by(bid_no="MB-IMMU-1").all()
        }
        assert before == after

    def test_failure_tag_a_value_missing(self, db_session):
        """A값 결측(실측 99.99%)이 태깅돼야 영향을 정량화할 수 있다."""
        self._prepare(db_session, "MB-TAG-1", winner=95_000_000)
        mb.score_pending(db_session)

        row = (db_session.query(models.MockBidResult)
               .join(models.MockBid)
               .filter(models.MockBid.bid_no == "MB-TAG-1",
                       models.MockBid.arm == "active").first())
        assert "A값_결측" in (row.failure_tags or [])

    def test_gap_metrics_computed(self, db_session):
        self._prepare(db_session, "MB-GAP-1", winner=95_000_000)
        mb.score_pending(db_session)

        row = (db_session.query(models.MockBidResult)
               .join(models.MockBid)
               .filter(models.MockBid.bid_no == "MB-GAP-1",
                       models.MockBid.arm == "standard").first())
        assert row.gap_to_winner_pct is not None
        assert row.gap_to_limit_pct is not None
        assert row.actual_lower_limit == pytest.approx(89_745_000, rel=1e-3)


# ── 집계 ──────────────────────────────────────────────────────

class TestSummary:
    def test_summarize_and_reach(self, db_session):
        n = _notice("MB-SUM-1")
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()
        db_session.add(_opening("MB-SUM-1", winner=95_000_000))
        db_session.commit()
        for row in db_session.query(models.MockBid).filter_by(bid_no="MB-SUM-1").all():
            row.deadline_at = mb.now_kst() - timedelta(hours=1)
        db_session.commit()
        mb.score_pending(db_session)

        s = mb.summarize(db_session)
        assert "standard" in s and s["standard"]["judged"] >= 1
        assert s["standard"]["dropout_rate"] is not None

        reach = mb.scoring_reach(db_session)
        notice_count = db_session.query(models.MockBid.bid_no).distinct().count()
        assert reach["registered"] == notice_count
        assert reach["unit"] == "notices"
        assert reach["gate_g_a_threshold"] == 60.0

    def test_failure_tag_stats(self, db_session):
        n = _notice("MB-SUM-2")
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()
        db_session.add(_opening("MB-SUM-2", winner=95_000_000))
        db_session.commit()
        for row in db_session.query(models.MockBid).filter_by(bid_no="MB-SUM-2").all():
            row.deadline_at = mb.now_kst() - timedelta(hours=1)
        db_session.commit()
        mb.score_pending(db_session)

        stats = mb.failure_tag_stats(db_session)
        assert "A값_결측" in stats
        assert stats["A값_결측"]["total"] >= 1

    def test_base_mismatch_is_excluded_and_reported(self, db_session):
        """추정가격이 스냅샷에 섞인 구 표본은 원장에 남기되 성적에서 뺀다."""
        before_arms = mb.summarize(db_session)
        before_validity = mb.sample_validity(db_session)
        before_standard = before_arms.get("standard", {})

        n = _notice("MB-SUM-BAD-BASE")
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()
        # 예정가격/등록 스냅샷 = 1.10 — 기초금액이 아니라 추정가격이 섞인 신호.
        db_session.add(_opening("MB-SUM-BAD-BASE", reserved=110_000_000,
                                winner=100_000_000))
        db_session.commit()
        for row in db_session.query(models.MockBid).filter_by(bid_no="MB-SUM-BAD-BASE").all():
            row.deadline_at = mb.now_kst() - timedelta(hours=1)
        db_session.commit()
        mb.score_pending(db_session)

        after_standard = mb.summarize(db_session)["standard"]
        after_validity = mb.sample_validity(db_session)

        assert after_standard["raw_judged"] == before_standard.get("raw_judged", 0) + 1
        assert after_standard["excluded_base_mismatch"] == (
            before_standard.get("excluded_base_mismatch", 0) + 1
        )
        assert after_standard["judged"] == before_standard.get("judged", 0)
        assert after_validity["registered_notices"] == (
            before_validity["registered_notices"] + 1
        )
        assert after_validity["raw_judged_notices"] == (
            before_validity["raw_judged_notices"] + 1
        )
        assert after_validity["excluded_base_mismatch"] == (
            before_validity["excluded_base_mismatch"] + 1
        )
        assert after_validity["valid_judged_notices"] == (
            before_validity["valid_judged_notices"]
        )

    def test_missing_reserved_price_is_reported_as_unknown(self, db_session):
        before = mb.sample_validity(db_session)
        n = _notice("MB-SUM-UNKNOWN-BASE")
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()
        db_session.add(_opening("MB-SUM-UNKNOWN-BASE", reserved=None,
                                winner=95_000_000))
        db_session.commit()
        for row in db_session.query(models.MockBid).filter_by(
                bid_no="MB-SUM-UNKNOWN-BASE").all():
            row.deadline_at = mb.now_kst() - timedelta(hours=1)
        db_session.commit()
        mb.score_pending(db_session)

        after = mb.sample_validity(db_session)
        assert after["excluded_base_unknown"] == before["excluded_base_unknown"] + 1
        assert after["valid_judged_notices"] == before["valid_judged_notices"]


class TestStrategyGates:
    @staticmethod
    def _arm(judged, win, dropout):
        lo, hi = mb.wilson_ci(win, judged)
        return {
            "judged": judged,
            "win": win,
            "dropout": dropout,
            "win_rate": round(win / judged * 100, 3) if judged else None,
            "dropout_rate": round(dropout / judged * 100, 3) if judged else None,
            "win_ci95": [round(lo, 3), round(hi, 3)] if judged else None,
        }

    def test_g_a_blocks_strategy_interpretation(self):
        gates = mb._evaluate_strategy_gates(
            {"status": "OBSERVING", "interpretation_allowed": False},
            {
                "standard": self._arm(400, 20, 40),
                "active": self._arm(400, 80, 20),
                "frontier_c10": self._arm(400, 160, 40),
            },
        )

        assert gates["g_b"]["status"] == "BLOCKED_G_A"
        assert gates["g_c"]["status"] == "LOCKED_G_B"

    def test_g_b_waits_for_400_distinct_notice_samples(self):
        gates = mb._evaluate_strategy_gates(
            {"status": "PASS", "interpretation_allowed": True},
            {
                "standard": self._arm(399, 20, 40),
                "active": self._arm(399, 80, 20),
            },
        )

        assert gates["g_b"]["sample_notices"] == 399
        assert gates["g_b"]["sample_requirement_met"] is False
        assert gates["g_b"]["status"] == "NOT_READY"

    def test_g_b_passes_only_when_dropout_and_wilson_conditions_hold(self):
        gates = mb._evaluate_strategy_gates(
            {"status": "PASS", "interpretation_allowed": True},
            {
                "standard": self._arm(400, 20, 40),
                "active": self._arm(400, 80, 20),
            },
        )

        assert gates["g_b"]["sample_requirement_met"] is True
        assert gates["g_b"]["active_dropout_lte_standard"] is True
        assert gates["g_b"]["active_win_ci_lower_gt_standard_upper"] is True
        assert gates["g_b"]["status"] == "PASS"

    def test_g_b_fails_when_active_dropout_is_higher(self):
        gates = mb._evaluate_strategy_gates(
            {"status": "PASS", "interpretation_allowed": True},
            {
                "standard": self._arm(400, 20, 20),
                "active": self._arm(400, 80, 40),
            },
        )

        assert gates["g_b"]["active_win_ci_lower_gt_standard_upper"] is True
        assert gates["g_b"]["active_dropout_lte_standard"] is False
        assert gates["g_b"]["status"] == "FAIL"

    def test_g_c_unlocks_after_g_b_and_applies_frontier_conditions(self):
        gates = mb._evaluate_strategy_gates(
            {"status": "PASS", "interpretation_allowed": True},
            {
                "standard": self._arm(400, 20, 40),
                "active": self._arm(400, 80, 20),
                "frontier_c10": self._arm(400, 160, 40),
            },
        )

        assert gates["g_b"]["status"] == "PASS"
        assert gates["g_c"]["frontier_c10_win_ci_lower_gt_active_upper"] is True
        assert gates["g_c"]["frontier_c10_dropout_condition_met"] is True
        assert gates["g_c"]["status"] == "PASS"


# ── Phase 2 — 참가자 데이터로 등수 재구성 (§4-3) ──────────────

def _participant(bid_no, rank, price, company="참가사", sucsf="N"):
    return models.OpeningParticipant(
        bid_no=bid_no, rank=rank, company=company, bid_price=price,
        bid_rate=round(price / 1e8 * 100, 4), sucsf_yn=sucsf,
    )


class TestEstimateRank:
    """등수는 판정(judge)의 대체가 아니라 별개 지표다 — API opengRank 와 같은 축."""

    def test_between_two_participants(self):
        assert mb.estimate_rank(90, [89, 91]) == 2

    def test_cheapest_is_first(self):
        assert mb.estimate_rank(88, [89, 91]) == 1

    def test_tie_shares_rank(self):
        """동가는 같은 순위 — 엄격히 낮은 가격만 앞선다."""
        assert mb.estimate_rank(90, [90, 91]) == 1

    def test_most_expensive_is_last(self):
        assert mb.estimate_rank(95, [89, 90, 91]) == 4


class TestParticipantScoring:
    def _prepare(self, db_session, bid_no, *, winner=90_000_000, participants=None):
        n = _notice(bid_no)
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()
        db_session.add(_opening(bid_no, winner=winner))
        for p in (participants or []):
            db_session.add(p)
        db_session.commit()
        for row in db_session.query(models.MockBid).filter_by(bid_no=bid_no).all():
            row.deadline_at = mb.now_kst() - timedelta(hours=1)
        db_session.commit()

    def test_rank_filled_at_first_scoring(self, db_session):
        """참가자 크롤(19:00)이 채점(20:30)보다 앞서므로 대부분 첫 채점에서 채워진다."""
        self._prepare(db_session, "MB-P2-1", winner=90_000_000, participants=[
            _participant("MB-P2-1", 1, 90_000_000, sucsf="Y"),
            _participant("MB-P2-1", 2, 92_000_000),
            _participant("MB-P2-1", 3, 95_000_000),
        ])
        mb.score_pending(db_session)

        row = (db_session.query(models.MockBidResult)
               .join(models.MockBid)
               .filter(models.MockBid.bid_no == "MB-P2-1",
                       models.MockBid.arm == "standard").first())
        # standard 등록가 97.5M > 참가자 전원 → 4위. 참여자 수는 실측 3명.
        assert row.estimated_rank == 4
        assert row.participants_count == 3

    def test_rank_none_without_participants(self, db_session):
        self._prepare(db_session, "MB-P2-2")
        mb.score_pending(db_session)

        row = (db_session.query(models.MockBidResult)
               .join(models.MockBid)
               .filter(models.MockBid.bid_no == "MB-P2-2").first())
        assert row.estimated_rank is None

    def test_backfill_creates_new_rev_not_update(self, db_session):
        """§0.5-3 — 참가자가 뒤늦게 도착해도 기존 결과 행은 UPDATE 하지 않는다."""
        self._prepare(db_session, "MB-P2-3")
        mb.score_pending(db_session)

        # 참가자가 채점 후에야 도착한 상황
        db_session.add(_participant("MB-P2-3", 1, 90_000_000, sucsf="Y"))
        db_session.add(_participant("MB-P2-3", 2, 93_000_000))
        db_session.commit()

        r = mb.backfill_participant_ranks(db_session)
        assert r["backfilled"] == 5  # 5 arm 전부

        rows = (db_session.query(models.MockBidResult)
                .join(models.MockBid)
                .filter(models.MockBid.bid_no == "MB-P2-3",
                        models.MockBid.arm == "standard")
                .order_by(models.MockBidResult.scoring_rev).all())
        assert len(rows) == 2
        assert rows[0].estimated_rank is None          # 기존 행 불변
        assert rows[1].scoring_rev == rows[0].scoring_rev + 1
        assert rows[1].estimated_rank == 3             # 97.5M > 2명 → 3위
        assert rows[1].outcome == rows[0].outcome      # 판정은 복사 — 등수만 더한다
        assert rows[1].participants_count == 2

    def test_backfill_is_idempotent(self, db_session):
        """최신 rev 에 등수가 채워지면 다음 실행은 아무것도 만들지 않는다."""
        self._prepare(db_session, "MB-P2-4")
        mb.score_pending(db_session)
        db_session.add(_participant("MB-P2-4", 1, 90_000_000, sucsf="Y"))
        db_session.commit()

        first = mb.backfill_participant_ranks(db_session)
        second = mb.backfill_participant_ranks(db_session)

        assert first["backfilled"] == 5
        assert second["backfilled"] == 0

    def test_registration_immutable_through_backfill(self, db_session):
        """등수 백필도 mock_bids 원장은 건드리지 않는다."""
        self._prepare(db_session, "MB-P2-5")
        mb.score_pending(db_session)
        db_session.add(_participant("MB-P2-5", 1, 90_000_000, sucsf="Y"))
        db_session.commit()

        before = {
            r.arm: (r.price, r.snapshot_basic_price, r.registered_at, r.status)
            for r in db_session.query(models.MockBid).filter_by(bid_no="MB-P2-5").all()
        }
        mb.backfill_participant_ranks(db_session)
        after = {
            r.arm: (r.price, r.snapshot_basic_price, r.registered_at, r.status)
            for r in db_session.query(models.MockBid).filter_by(bid_no="MB-P2-5").all()
        }
        assert before == after

    def test_summarize_counts_latest_rev_only(self, db_session):
        """재채점이 새 rev 를 쌓아도 같은 등록 건이 중복 집계되면 안 된다."""
        self._prepare(db_session, "MB-P2-6")
        mb.score_pending(db_session)
        before = mb.summarize(db_session).get("standard", {}).get("judged", 0)

        db_session.add(_participant("MB-P2-6", 1, 90_000_000, sucsf="Y"))
        db_session.commit()
        mb.backfill_participant_ranks(db_session)

        after = mb.summarize(db_session).get("standard", {}).get("judged", 0)
        assert after == before  # rev 가 늘어도 judged 는 그대로


class TestChartAggregates:
    """시각화 집계 — 전부 최신 rev 기준. 데이터 형태만 계약으로 고정한다."""

    def _prepare_scored(self, db_session, bid_no):
        n = _notice(bid_no)
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()
        db_session.add(_opening(bid_no, winner=95_000_000))
        db_session.add(_participant(bid_no, 1, 95_000_000, sucsf="Y"))
        db_session.add(_participant(bid_no, 2, 96_000_000))
        db_session.commit()
        for row in db_session.query(models.MockBid).filter_by(bid_no=bid_no).all():
            row.deadline_at = mb.now_kst() - timedelta(hours=1)
        db_session.commit()
        mb.score_pending(db_session)

    def test_rank_distribution_shape(self, db_session):
        self._prepare_scored(db_session, "MB-CH-1")
        dist = mb.rank_distribution(db_session)
        assert "standard" in dist
        # standard(97.5M)는 두 참가자보다 높아 3위 버킷에 1건 이상
        assert dist["standard"].get("3", 0) >= 1

    def test_gap_distribution_uses_fixed_buckets(self, db_session):
        self._prepare_scored(db_session, "MB-CH-2")
        dist = mb.gap_distribution(db_session)
        assert "standard" in dist
        for bucket in dist["standard"]:
            assert bucket in mb.GAP_BUCKETS

    def test_ratio_error_trend_active_only(self, db_session):
        self._prepare_scored(db_session, "MB-CH-3")
        trend = mb.ratio_error_trend(db_session, arm="active")
        assert trend, "active arm 은 adjustment 를 기록하므로 오차가 있어야 한다"
        assert {"date", "mean_error", "n"} <= set(trend[0].keys())

    def test_segment_stats_bracket_vocab(self, db_session):
        """금액대 어휘는 autocalibrate dataset.get_bracket 과 동일해야 한다."""
        from app.services.autocalibrate.dataset import BRACKETS

        self._prepare_scored(db_session, "MB-CH-4")
        rows = mb.segment_stats(db_session, arm="standard")
        assert rows
        for r in rows:
            assert r["bracket"] in BRACKETS
        # 기초금액 1억 = medium (1e8 은 small 상한 밖)
        assert any(r["bracket"] == "medium" and r["bid_method"] == "적격심사제" for r in rows)

    def test_base_mismatch_does_not_enter_chart_aggregates(self, db_session):
        """성적표뿐 아니라 차트·오답노트도 같은 유효 표본만 써야 한다."""
        before_segments = mb.segment_stats(db_session, arm="active")
        before_gaps = mb.gap_distribution(db_session)
        before_tags = mb.failure_tag_stats(db_session)

        n = _notice("MB-CH-BAD-BASE")
        db_session.add(n)
        db_session.commit()
        mb.register_notice(db_session, n)
        db_session.commit()
        db_session.add(_opening("MB-CH-BAD-BASE", reserved=110_000_000,
                                winner=100_000_000))
        db_session.commit()
        for row in db_session.query(models.MockBid).filter_by(bid_no="MB-CH-BAD-BASE").all():
            row.deadline_at = mb.now_kst() - timedelta(hours=1)
        db_session.commit()
        mb.score_pending(db_session)

        assert mb.segment_stats(db_session, arm="active") == before_segments
        assert mb.gap_distribution(db_session) == before_gaps
        assert mb.failure_tag_stats(db_session) == before_tags


class TestScoringBacklogOrder:
    """잔량이 limit 을 넘을 때의 계약 (2026-08-03 발견).

    낙찰자 확정에 며칠 걸리는 동안 NO_RESULT 등록분이 매일 다시 대상이 된다.
    하루 등록이 1,400건 규모라 나흘이면 limit(5000)에 닿는데, 정렬이 없으면
    잘려 나간 쪽이 매일 같은 자리에 남아 **영영 채점되지 않는다**.
    로그는 `scored: 5000` 이라 정상처럼 보이므로 조용히 샌다.
    """

    def _register_with_deadline(self, db_session, bid_no, hours_ago):
        n = _notice(bid_no)
        db_session.add(n)
        db_session.flush()
        mb.register_notice(db_session, n)
        db_session.flush()
        for row in db_session.query(models.MockBid).filter_by(bid_no=bid_no).all():
            row.deadline_at = mb.now_kst() - timedelta(hours=hours_ago)
        db_session.flush()

    def test_oldest_deadline_is_scored_first(self, db_session):
        """마감이 오래된 것부터 — 잘려도 다음 회차에 이어서 잡히도록."""
        self._register_with_deadline(db_session, "MB-ORD-NEW", hours_ago=1)
        self._register_with_deadline(db_session, "MB-ORD-OLD", hours_ago=72)

        r = mb.score_pending(db_session, limit=5)
        assert r["pending"] == 5

        scored_ids = {res.mock_bid_id for res in db_session.query(models.MockBidResult).all()}
        old_ids = {row.id for row in
                   db_session.query(models.MockBid).filter_by(bid_no="MB-ORD-OLD").all()}
        assert old_ids <= scored_ids, "마감이 오래된 등록분이 먼저 채점돼야 한다"

    def test_deferred_count_is_reported(self, db_session):
        """잘린 잔량을 반환값에 남긴다 — 조용한 절삭 금지.

        다른 테스트가 커밋한 행이 섞이므로(픽스처는 rollback 만 한다) 절대값이
        아니라 '대상 − 처리' 로 검증한다.
        """
        self._register_with_deadline(db_session, "MB-ORD-A", hours_ago=10)
        self._register_with_deadline(db_session, "MB-ORD-B", hours_ago=9)

        due = (db_session.query(models.MockBid)
               .filter(models.MockBid.status == "REGISTERED",
                       models.MockBid.deadline_at < mb.now_kst())
               .count())
        r = mb.score_pending(db_session, limit=5)
        assert r["pending"] == 5
        assert r["deferred"] == due - 5, r

    def test_no_deferred_when_all_fit(self, db_session):
        self._register_with_deadline(db_session, "MB-ORD-C", hours_ago=3)
        r = mb.score_pending(db_session, limit=100)
        assert r["deferred"] == 0

    def test_unchecked_notice_is_not_starved_by_old_no_result(self, db_session):
        """오래된 NO_RESULT 가 매번 limit 을 독점해 신규가 영영 밀리면 안 된다.

        1회차에서 OLD 는 NO_RESULT 가 되고, 2회차 직전에 NEW 를 등록한다.
        단순 deadline 정렬이면 OLD 가 또 선택돼 NEW 는 결과 행조차 못 얻는다.
        """
        self._register_with_deadline(db_session, "MB-ORD-STALE", hours_ago=72)
        first = mb.score_pending(db_session, limit=5)
        assert first["outcomes"] == {"NO_RESULT": 5}

        self._register_with_deadline(db_session, "MB-ORD-UNCHECKED", hours_ago=1)
        second = mb.score_pending(db_session, limit=5)

        unchecked_ids = {
            row.id for row in db_session.query(models.MockBid)
            .filter_by(bid_no="MB-ORD-UNCHECKED").all()
        }
        result_ids = {
            row.mock_bid_id for row in db_session.query(models.MockBidResult)
            .filter(models.MockBidResult.mock_bid_id.in_(unchecked_ids)).all()
        }
        assert second["outcomes"] == {"NO_RESULT": 5}
        assert result_ids == unchecked_ids

    def test_available_opening_result_has_first_priority(self, db_session):
        """개찰결과가 이미 도착한 건은 오래된 NO_RESULT 보다 먼저 확정 채점한다."""
        self._register_with_deadline(db_session, "MB-ORD-WAIT", hours_ago=72)
        mb.score_pending(db_session, limit=5)  # WAIT 에 NO_RESULT rev1

        self._register_with_deadline(db_session, "MB-ORD-READY", hours_ago=1)
        db_session.add(_opening("MB-ORD-READY", winner=95_000_000))
        db_session.commit()

        r = mb.score_pending(db_session, limit=5)

        assert r["scored"] == 5
        assert "NO_RESULT" not in r["outcomes"]
        ready = db_session.query(models.MockBid).filter_by(bid_no="MB-ORD-READY").all()
        assert {row.status for row in ready} == {"SCORED"}

    def test_queue_health_explains_each_priority_bucket(self, db_session):
        self._register_with_deadline(db_session, "MB-QH-RETRY", hours_ago=72)
        mb.score_pending(db_session, limit=5)

        self._register_with_deadline(db_session, "MB-QH-FRESH", hours_ago=2)
        self._register_with_deadline(db_session, "MB-QH-READY", hours_ago=1)
        db_session.add(_opening("MB-QH-READY", winner=95_000_000))
        db_session.commit()

        health = mb.score_queue_health(
            db_session,
            bid_nos=["MB-QH-RETRY", "MB-QH-FRESH", "MB-QH-READY"],
        )

        assert health["due_arm_rows"] == 15
        assert health["due_notices"] == 3
        assert health["ready_with_opening_result_arm_rows"] == 5
        assert health["never_checked_arm_rows"] == 5
        assert health["retry_no_result_arm_rows"] == 5
        assert health["priority_order"] == [
            "ready_with_opening_result", "never_checked", "retry_no_result",
        ]


class TestRegisterRefreshesBasis:
    """등록 직전 기초금액 갱신 (2026-08-06 실측 근거).

    기초금액 공개는 09~11시에 몰리는데 수집 배치는 매일 06:40 한 번이라,
    공개분 대부분이 우리 수집 이후에 나온다. 그 탓에 등록이 no_basis_amount
    로 대량 스킵됐다 — 제도가 아니라 **우리 수집 주기가 병목**이었다.
    """

    def test_refresh_runs_before_registration(self, monkeypatch):
        from app.tasks import mock_bid_tasks as t

        order = []
        monkeypatch.setattr(t, "_refresh_basis_amounts",
                            lambda: (order.append("refresh"), {"updated": 3})[1])
        monkeypatch.setattr(t, "SessionLocal", lambda: _NullDB())
        monkeypatch.setattr(
            "app.services.mock_bidding.register_due_notices",
            lambda db, **k: (order.append("register"), {"registered": 5})[1])

        r = t.register_mock_bids()

        assert order == ["refresh", "register"], "갱신이 등록보다 먼저여야 한다"
        assert r["basis_refresh"] == {"updated": 3}

    def test_refresh_failure_does_not_block_registration(self, monkeypatch):
        """갱신 실패가 등록을 되돌리면 안 된다 — 보유분으로라도 등록한다."""
        from app.tasks import mock_bid_tasks as t

        def boom(*a, **k):
            raise RuntimeError("API 500")

        monkeypatch.setattr("app.services.basis_amount_crawler.crawl_recent", boom)
        monkeypatch.setattr(t, "SessionLocal", lambda: _NullDB())
        monkeypatch.setattr("app.services.mock_bidding.register_due_notices",
                            lambda db, **k: {"registered": 7})

        r = t.register_mock_bids()

        assert r["registered"] == 7
        assert "error" in r["basis_refresh"]

    def test_can_be_disabled(self, monkeypatch):
        from app.tasks import mock_bid_tasks as t

        called = []
        monkeypatch.setattr(t, "_refresh_basis_amounts",
                            lambda: called.append(1))
        monkeypatch.setattr(t, "SessionLocal", lambda: _NullDB())
        monkeypatch.setattr("app.services.mock_bidding.register_due_notices",
                            lambda db, **k: {"registered": 0})

        r = t.register_mock_bids(refresh_basis=False)

        assert called == []
        assert "basis_refresh" not in r


class TestWeeklyReport:
    def test_report_contains_gate_quality_queue_and_notes(self, db_session):
        report = mb.collect_weekly_report(
            db_session, now=datetime(2026, 8, 10, 21, 0),
        )

        assert report["period_key"] == "2026-W33"
        assert set(report["gates"]) == {"g_a", "g_b", "g_c"}
        assert "valid_judged_notices" in report["sample_validity"]
        assert "due_arm_rows" in report["queue_health"]
        assert isinstance(report["top_failure_tags"], dict)

    def test_task_is_idempotent_per_admin_and_week(self, db_session, monkeypatch):
        from app.tasks import mock_bid_tasks as t

        email = "mock-weekly-admin@test.com"
        admin = db_session.query(models.User).filter_by(email=email).first()
        if admin is None:
            admin = models.User(
                email=email, hashed_password="x", is_admin=True, tier="free",
            )
            db_session.add(admin)
            db_session.commit()
        admin_id = admin.id
        monkeypatch.setattr(t, "SessionLocal", lambda: db_session)
        fixed_report = mb.collect_weekly_report(
            db_session, now=datetime(2026, 8, 10, 21, 0),
        )
        monkeypatch.setattr(
            "app.services.mock_bidding.collect_weekly_report",
            lambda db: fixed_report,
        )

        first = t.weekly_mock_bid_report()
        second = t.weekly_mock_bid_report()

        assert first["ok"] is True
        assert first["notifications_created"] >= 1
        assert second["notifications_created"] == 0
        assert db_session.query(models.Notification).filter(
            models.Notification.user_id == admin_id,
            models.Notification.noti_type == "MOCK_BID_WEEKLY_2026-W33",
        ).count() == 1


class _NullDB:
    def rollback(self):
        pass

    def close(self):
        pass
