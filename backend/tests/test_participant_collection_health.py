"""참가자 수집 건전성 — 복구 경로와 일일 리포트 경보.

참가자 수집이 멈추면 모의투찰 등수 지표가 **조용히** 성장을 멈춘다. 크롤은
초록불이고 화면은 "참가자 데이터 대기"와 구분되지 않아 며칠이 지나도 아무도
모른다. 그래서 ① 사람이 손댈 수 있는 복구 경로와 ② 사람에게 실제로 닿는
경보가 함께 있어야 한다.

경보의 판정 기준이 두 번 갈아엎였다. **시각으로 판정하면 안 된다**:
- 절대 임계(30h·80h)는 주말·연휴마다 오탐이다.
- 개찰 결과와의 시각 차분도 같다. 둘은 **같은 일일 크롤에서 찍히므로** 고장
  첫날 관측되는 차이는 24h 한 값뿐이고, 어떤 임계도 크롤 주기 위에 놓인다.
  게다가 모수가 다르다 — 참가자는 등록 공고만, 개찰은 전 공고다.

그래서 **모수가 같은 사실 하나**를 본다: 최근 개찰이 확정된 등록 공고 중
참가자 행이 없는 비율.
"""
from datetime import date, datetime, timedelta, timezone

from app.db import models
from app.services.admin_daily_report import collect_daily_report

NOW = datetime.now(timezone.utc).replace(tzinfo=None)


class TestManualTriggerDaysBack:
    """정기 크롤 창 밖에서 확정된 개찰을 뒤늦게 줍는 경로."""

    def test_days_back_rejected_for_tasks_that_do_not_take_it(self, admin_client):
        """인자를 안 받는 태스크에 넘기면 워커에서 TypeError 로 죽는다."""
        r = admin_client.post(
            "/api/v1/admin/system/tasks/trial.send_expiry_reminders/trigger",
            params={"days_back": 7},
        )
        assert r.status_code == 400
        assert "days_back" in r.json()["detail"]

    def test_days_back_range_is_bounded(self, admin_client):
        r = admin_client.post(
            "/api/v1/admin/system/tasks/verification.daily_crawl_opening_results/trigger",
            params={"days_back": 999},
        )
        assert r.status_code == 400

    def test_zero_is_rejected_as_a_silent_noop(self, admin_client):
        """0 이면 길이 0 짜리 창이라 아무 일도 안 하고 '성공'으로 보고된다."""
        r = admin_client.post(
            "/api/v1/admin/system/tasks/verification.daily_crawl_opening_results/trigger",
            params={"days_back": 0},
        )
        assert r.status_code == 400

    def test_limit_is_per_task(self, admin_client):
        """예측 검증은 API 호출이 0 이고 스케줄 기본값이 30 이다.

        개찰 크롤 기준(7)을 일괄로 씌우면 그 태스크는 **자기 기본값조차** 수동
        으로 넣을 수 없다.
        """
        r = admin_client.post(
            "/api/v1/admin/system/tasks/verification.daily_verify_predictions/trigger",
            params={"days_back": 30},
        )
        assert r.status_code == 200

    def test_unknown_task_still_rejected(self, admin_client):
        r = admin_client.post(
            "/api/v1/admin/system/tasks/evil.task/trigger",
            params={"days_back": 3},
        )
        assert r.status_code == 400


class TestDailyReportParticipantAlarm:
    """새 경보에는 소비자가 있어야 한다 — 태스크 FAILURE 로그는 보는 사람이 없다."""

    @staticmethod
    def _report(db, *, opened=(), with_participants=()):
        """개찰이 확정된 등록 공고를 만들고 리포트를 돌린다.

        이 검사는 테이블 전체를 보므로 앞 테스트가 남긴 행을 치우고 시작한다.
        `opened` 는 (bid_no, 개찰 경과일) 목록, `with_participants` 는 그중
        참가자 행이 있는 bid_no 다.
        """
        db.query(models.OpeningParticipant).delete()
        db.query(models.OpeningResult).delete()
        db.query(models.MockBid).delete()
        for bid_no, days_ago in opened:
            db.add(models.MockBid(
                bid_no=bid_no, arm="standard", registered_at=NOW,
                deadline_at=NOW - timedelta(days=days_ago),
                price=97_500_000, snapshot_basic_price=100_000_000,
                status="REGISTERED",
            ))
            db.add(models.OpeningResult(
                bid_no=bid_no, basic_price=100_000_000, reserved_price=100_000_000,
                winner_price=90_000_000, open_date=NOW - timedelta(days=days_ago),
            ))
            if bid_no in with_participants:
                db.add(models.OpeningParticipant(
                    bid_no=bid_no, rank=1, company="A건설", bid_price=90_000_000,
                    bid_rate=90.0, sucsf_yn="N", crawled_at=NOW,
                ))
        db.commit()
        return collect_daily_report(db, date.today())

    @staticmethod
    def _alarmed(report):
        return any("참가자" in a for a in report["anomalies"])

    def test_silent_when_nothing_opened(self, db_session):
        """개찰이 없으면 분모가 0 이라 조용하다 — 주말·연휴 면역의 핵심."""
        assert not self._alarmed(self._report(db_session))

    def test_silent_when_participants_are_collected(self, db_session):
        """정상 상태 — 실측 2026-08-12 기준 누락 0건이 baseline 이다."""
        opened = [(f"OK-{i}", 1) for i in range(8)]
        report = self._report(db_session, opened=opened,
                              with_participants={b for b, _ in opened})
        assert not self._alarmed(report)

    def test_alarms_when_most_opened_notices_have_no_participants(self, db_session):
        """개찰은 났는데 참가자가 안 붙는다 = 수집 경로가 죽었다."""
        opened = [(f"DEAD-{i}", 1) for i in range(8)]
        report = self._report(db_session, opened=opened, with_participants=set())
        assert self._alarmed(report)

    def test_small_residue_does_not_alarm(self, db_session):
        """한두 건 누락은 정상 잔여다 — 크롤 창 경계에서 늘 생긴다.

        절대 건수 1건으로 경보하면 매일 뜨고, 매일 뜨는 경보는 무시된다.
        """
        opened = [(f"MIX-{i}", 1) for i in range(10)]
        report = self._report(db_session, opened=opened,
                              with_participants={f"MIX-{i}" for i in range(8)})
        assert not self._alarmed(report)

    def test_old_openings_are_out_of_scope(self, db_session):
        """3일 창 밖에서 확정된 개찰은 분모에서 빠진다.

        Phase 2 이전 등록분처럼 참가자가 영영 안 붙는 과거 건이 분모에 남으면
        경보가 상시 켜진 채 무시된다.
        """
        opened = [(f"OLD-{i}", 10) for i in range(8)]
        report = self._report(db_session, opened=opened, with_participants=set())
        assert not self._alarmed(report)
