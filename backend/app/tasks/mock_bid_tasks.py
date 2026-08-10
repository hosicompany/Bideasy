"""모의투찰 Celery 태스크 — 사전 등록 / 채점 / 주간 성적표.

설계 정본: `docs/MOCK_BIDDING_DESIGN.md`

스케줄 (celery_app.py, 시각=KST):
- 매시 15분: `mock_bid.register` — 마감 2h 이내 공고를 arm 별 사전 등록
- 20:30    : `mock_bid.score`    — 개찰결과 도착분 채점
- 월 21:00 : `mock_bid.weekly_report` — 게이트·표본품질·오답노트 스냅샷

**왜 매시인가**: 마감시각이 공고마다 다르다. 하루 1회로는 "마감 전 등록"을
보장할 수 없고, 마감이 지나 등록하면 이 실험 자체가 무의미해진다.
개찰결과 크롤(19:00)보다 채점을 뒤에 두어 같은 날 개찰분을 잡는다.
"""

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal

logger = get_logger(__name__)


def _refresh_basis_amounts() -> dict:
    """등록 직전 기초금액 갱신 — 실패해도 등록을 막지 않는다.

    **역할은 "오늘 새로 공개된 것 줍기"** 다(창 = `REFRESH_LOOKBACK_DAYS`).

    기초금액은 마감 **6~8일 전**에 몰려 공개되므로(실측 D-6 에 144건) 그 몫은
    일일 배치(`DEFAULT_LOOKBACK_DAYS` = 14일 창)가 이미 잡아 둔다. 여기서 같은
    긴 창을 매시 도는 건 낭비다.

    ⚠️ 한때 "수집 주기(06:40)가 병목"이라고 진단했으나 틀렸다. 그때 본 것은
    **하루 안의 시각 분포**(09~11시 집중)였고, 실제 병목은 **조회 창**이었다
    — 창 3일이면 매칭 9.3%, 14일이면 75.3%. 두 축을 혼동한 오진이었다.
    경위: docs/PRICE_BASE_DEFECT.md
    """
    from app.services.basis_amount_crawler import REFRESH_LOOKBACK_DAYS, crawl_recent

    try:
        return crawl_recent(days_back=REFRESH_LOOKBACK_DAYS)
    except Exception as e:  # noqa: BLE001
        # 갱신 실패는 등록을 되돌리지 않는다 — 기존 보유분으로 진행한다
        logger.warning(f"[mock_bid.register] 기초금액 갱신 실패(등록은 계속): {e}")
        return {"error": str(e)}


@celery_app.task(name="mock_bid.register")
def register_mock_bids(window_hours: int = 2, limit: int = 2000,
                       refresh_basis: bool = True) -> dict:
    """마감 임박 공고를 5 arm 으로 사전 등록.

    등록 전에 기초금액을 갱신한다(`refresh_basis=False` 로 끌 수 있다).
    """
    from app.services.mock_bidding import register_due_notices

    basis_stats = _refresh_basis_amounts() if refresh_basis else None

    db = SessionLocal()
    try:
        result = register_due_notices(db, window_hours=window_hours, limit=limit)
        if basis_stats is not None:
            result["basis_refresh"] = basis_stats
        return result
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"[mock_bid.register] error: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(name="mock_bid.score")
def score_mock_bids(limit: int = 5000) -> dict:
    """마감이 지난 미채점 등록분을 개찰결과와 대조해 채점.

    채점 뒤에 등수 백필을 이어 돈다 — 참가자 크롤(19:00)이 채점 대상보다
    늦게 붙은 건(적격검사 지연 등)의 등수를 새 scoring_rev 로 채운다(§0.5-3).
    """
    from app.services.mock_bidding import backfill_participant_ranks, score_pending

    db = SessionLocal()
    try:
        result = score_pending(db, limit=limit)
        # 등수 백필 실패가 채점 결과를 가리지 않도록 분리해서 잡는다
        try:
            result["rank_backfill"] = backfill_participant_ranks(db, limit=limit)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.error(f"[mock_bid.score] rank backfill error: {e}", exc_info=True)
            result["rank_backfill"] = {"error": str(e)}
        return result
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"[mock_bid.score] error: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(name="mock_bid.weekly_report")
def weekly_mock_bid_report() -> dict:
    """월요일 채점 뒤 누적 성적표를 관리자 인앱 알림으로 한 번만 남긴다."""
    from app.services.mock_bidding import collect_weekly_report

    db = SessionLocal()
    try:
        report = collect_weekly_report(db)
        noti_type = f"MOCK_BID_WEEKLY_{report['period_key']}"
        g_a = report["gates"]["g_a"]
        g_b = report["gates"]["g_b"]
        g_c = report["gates"]["g_c"]
        validity = report["sample_validity"]
        reach_label = (
            f"{g_a['reach_pct']}%" if g_a["reach_pct"] is not None else "—"
        )
        body = (
            f"G-A {g_a['status']} ({reach_label}), "
            f"G-B {g_b['status']}, G-C {g_c['status']} · "
            f"유효 {validity['valid_judged_notices']}공고"
        )

        created = 0
        admins = db.query(models.User).filter(models.User.is_admin == True).all()  # noqa: E712
        for admin in admins:
            exists_for_week = db.query(models.Notification.id).filter(
                models.Notification.user_id == admin.id,
                models.Notification.noti_type == noti_type,
            ).first()
            if exists_for_week:
                continue
            db.add(models.Notification(
                user_id=admin.id,
                title=f"📊 모의투찰 주간 성적표 — {report['period_key']}",
                body=body,
                noti_type=noti_type,
                data_json={"report": report},
                is_read=0,
            ))
            created += 1
        db.commit()
        logger.info(
            f"[mock_bid.weekly_report] period={report['period_key']} "
            f"notifications={created} G-A={g_a['status']} "
            f"G-B={g_b['status']} G-C={g_c['status']}"
        )
        return {
            "ok": True,
            "period_key": report["period_key"],
            "notifications_created": created,
            "gate_statuses": {
                "g_a": g_a["status"],
                "g_b": g_b["status"],
                "g_c": g_c["status"],
            },
        }
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"[mock_bid.weekly_report] error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
    finally:
        db.close()
