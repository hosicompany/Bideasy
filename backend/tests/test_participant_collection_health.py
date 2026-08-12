"""참가자 수집 건전성 — 복구 경로와 일일 리포트 경보.

참가자 수집이 멈추면 모의투찰 등수 지표가 **조용히** 성장을 멈춘다. 크롤은
초록불이고 화면은 "참가자 데이터 대기"와 구분되지 않아 며칠이 지나도 아무도
모른다. 그래서 ① 사람이 손댈 수 있는 복구 경로와 ② 사람에게 실제로 닿는
경보가 함께 있어야 한다.
"""
from datetime import date, datetime, timedelta, timezone

from app.db import models
from app.services.admin_daily_report import collect_daily_report


class TestManualTriggerDaysBack:
    """축소 가드에 걸린 공고를 푸는 유일한 경로 — 창을 넓혀 재크롤."""

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

    def test_unknown_task_still_rejected(self, admin_client):
        r = admin_client.post(
            "/api/v1/admin/system/tasks/evil.task/trigger",
            params={"days_back": 3},
        )
        assert r.status_code == 400


class TestDailyReportParticipantAlarm:
    """새 경보에는 소비자가 있어야 한다 — 태스크 FAILURE 로그는 보는 사람이 없다."""

    @staticmethod
    def _report(db, *, participants=(), mock_bids=(), openings=()):
        """이 검사는 테이블 전체를 보므로, 앞 테스트가 남긴 행을 치우고 시작한다."""
        db.query(models.OpeningParticipant).delete()
        db.query(models.OpeningResult).delete()
        db.query(models.MockBid).delete()
        for row in (*mock_bids, *openings, *participants):
            db.add(row)
        db.commit()
        return collect_daily_report(db, date.today())

    @staticmethod
    def _mock_bid(bid_no, *, hours_to_deadline):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return models.MockBid(
            bid_no=bid_no, arm="standard", registered_at=now,
            deadline_at=now + timedelta(hours=hours_to_deadline),
            price=97_500_000, snapshot_basic_price=100_000_000, status="REGISTERED",
        )

    @staticmethod
    def _participant(bid_no, *, hours_ago):
        return models.OpeningParticipant(
            bid_no=bid_no, rank=1, company="A건설", bid_price=90_000_000,
            bid_rate=90.0, sucsf_yn="N",
            crawled_at=datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(hours=hours_ago),
        )

    def test_silent_when_nothing_registered_yet(self, db_session):
        """등록 자체가 없으면 참가자가 없는 게 당연하다 — 경보 금지."""
        report = self._report(db_session)
        assert not any("참가자" in a for a in report["anomalies"])

    def test_silent_while_registered_notices_are_not_opened_yet(self, db_session):
        """등록은 됐지만 아직 개찰 전 — 참가자가 없는 게 정상이다.

        "등록이 있다"로 판정하면 착수 직후 매일 오탐이 뜬다.
        """
        report = self._report(db_session, mock_bids=[
            self._mock_bid("HEALTH-PENDING-000", hours_to_deadline=2)])
        assert not any("참가자" in a for a in report["anomalies"])

    def test_alarms_when_opened_notice_has_no_participants(self, db_session):
        """개찰까지 났는데 참가자가 한 건도 없다 = 수집 경로가 죽었다.

        배포 직후 이 상태가 **가장 위험한데**, 테이블이 비어 있다는 이유로
        침묵하던 구간이었다.
        """
        report = self._report(
            db_session,
            mock_bids=[self._mock_bid("HEALTH-OPENED-000", hours_to_deadline=-2)],
            openings=[models.OpeningResult(
                bid_no="HEALTH-OPENED-000", basic_price=100_000_000,
                reserved_price=100_000_000, winner_price=90_000_000,
                open_date=datetime.now(timezone.utc).replace(tzinfo=None),
            )],
        )
        assert any("참가자" in a for a in report["anomalies"])

    @staticmethod
    def _opening(bid_no, *, hours_ago):
        return models.OpeningResult(
            bid_no=bid_no, basic_price=100_000_000, reserved_price=100_000_000,
            winner_price=90_000_000,
            open_date=datetime.now(timezone.utc).replace(tzinfo=None),
            crawled_at=datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(hours=hours_ago),
        )

    def test_weekend_gap_does_not_alarm(self, db_session):
        """주말엔 개찰이 없어 **둘 다** 멈춘다 — 정상이다.

        절대 시간 임계였을 때는 30h 든 80h 든 주말·연휴마다 떴다. 매주 뜨는
        경보는 곧 무시된다.
        """
        report = self._report(
            db_session,
            participants=[self._participant("HEALTH-WEEKEND-000", hours_ago=40)],
            openings=[self._opening("HEALTH-WEEKEND-000", hours_ago=40)],
        )
        assert not any("참가자" in a for a in report["anomalies"])

    def test_long_holiday_does_not_alarm(self, db_session):
        """설·추석 5일 연휴에도 조용해야 한다 — 절대 임계로는 불가능했다."""
        report = self._report(
            db_session,
            participants=[self._participant("HEALTH-HOLIDAY-000", hours_ago=110)],
            openings=[self._opening("HEALTH-HOLIDAY-000", hours_ago=110)],
        )
        assert not any("참가자" in a for a in report["anomalies"])

    def test_alarms_when_openings_advance_but_participants_do_not(self, db_session):
        """개찰 결과는 들어오는데 참가자만 멈췄다 = 참가자 경로만 고장.

        이건 연휴와 달리 진짜 이상이고, 하루 안에 잡혀야 한다.
        """
        report = self._report(
            db_session,
            participants=[self._participant("HEALTH-BEHIND-000", hours_ago=50)],
            openings=[self._opening("HEALTH-BEHIND-000", hours_ago=2)],
        )
        assert any("참가자" in a for a in report["anomalies"])
