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


def _refresh_basis_amounts() -> dict:
    """등록 직전 기초금액 갱신 — 실패해도 등록을 막지 않는다.

    **왜 등록 직전인가** (2026-08-06 실측):
    기초금액 공개는 09~11시에 몰린다(46·50·36건). 그런데 수집 배치는 매일
    06:40 한 번이라, **공개분의 대부분이 우리 수집 이후에 나온다.** 오늘
    09시에 공개된 기초금액은 내일 06:40 에야 들어오는데 그 공고 마감은 오늘
    11~12시다 — 구조적으로 항상 늦는다.

    그 탓에 등록이 `no_basis_amount` 로 대량 스킵됐다(신규 후보의 50~98%).
    제도가 안 알려줘서가 아니라 **우리 수집 주기가 병목**이었다.
    등록이 매시 :15 에 도니 그 직전에 당일분을 당겨오면 가용률이 실측
    수준(등록 시점 기준 75.7%)으로 회복된다.

    하루 물량이 150~300건이라 매시 호출해도 API 콜 몇 번이면 끝난다(멱등).
    """
    from app.services.basis_amount_crawler import crawl_recent

    try:
        return crawl_recent(days_back=1)
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
