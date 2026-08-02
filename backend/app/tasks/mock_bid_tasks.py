"""모의투찰 Celery 태스크 — 사전 등록 / 채점.

설계 정본: `docs/MOCK_BIDDING_DESIGN.md`

스케줄 (celery_app.py, 시각=KST):
- 매시 15분: `mock_bid.register` — 마감 2h 이내 공고를 arm 별 사전 등록
- 20:30    : `mock_bid.score`    — 개찰결과 도착분 채점

**왜 매시인가**: 마감시각이 공고마다 다르다. 하루 1회로는 "마감 전 등록"을
보장할 수 없고, 마감이 지나 등록하면 이 실험 자체가 무의미해진다.
개찰결과 크롤(19:00)보다 채점을 뒤에 두어 같은 날 개찰분을 잡는다.
"""

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db.session import SessionLocal

logger = get_logger(__name__)


@celery_app.task(name="mock_bid.register")
def register_mock_bids(window_hours: int = 2, limit: int = 2000) -> dict:
    """마감 임박 공고를 5 arm 으로 사전 등록."""
    from app.services.mock_bidding import register_due_notices

    db = SessionLocal()
    try:
        return register_due_notices(db, window_hours=window_hours, limit=limit)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"[mock_bid.register] error: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(name="mock_bid.score")
def score_mock_bids(limit: int = 5000) -> dict:
    """마감이 지난 미채점 등록분을 개찰결과와 대조해 채점."""
    from app.services.mock_bidding import score_pending

    db = SessionLocal()
    try:
        return score_pending(db, limit=limit)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"[mock_bid.score] error: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
