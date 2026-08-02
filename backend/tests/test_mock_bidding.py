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
        end_date=datetime.now() + timedelta(hours=end_offset_h),
        prdprc_total=prdprc[0], prdprc_draw=prdprc[1], re_notice_yn=re_notice,
    )


def _opening(bid_no="MB-1", *, basic=100_000_000, reserved=100_000_000,
             winner=90_000_000):
    return models.OpeningResult(
        bid_no=bid_no, basic_price=basic, reserved_price=reserved,
        winner_price=winner, winner_rate=winner / basic * 100,
        open_date=datetime.now(),
    )


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

    def test_no_basic_price_excluded(self):
        ok, reason = mb.is_eligible(_notice(basic_price=0))
        assert ok is False and reason == "no_basic_price"


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
            row.deadline_at = datetime.now() - timedelta(hours=1)
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
            row.deadline_at = datetime.now() - timedelta(hours=1)
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
            row.deadline_at = datetime.now() - timedelta(hours=1)
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
            row.deadline_at = datetime.now() - timedelta(hours=1)
        db_session.commit()
        mb.score_pending(db_session)

        s = mb.summarize(db_session)
        assert "standard" in s and s["standard"]["judged"] >= 1
        assert s["standard"]["dropout_rate"] is not None

        reach = mb.scoring_reach(db_session)
        assert reach["registered"] >= 5
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
            row.deadline_at = datetime.now() - timedelta(hours=1)
        db_session.commit()
        mb.score_pending(db_session)

        stats = mb.failure_tag_stats(db_session)
        assert "A값_결측" in stats
        assert stats["A값_결측"]["total"] >= 1
