"""관리자 — 모의투찰(Shadow Bidding) 조회.

설계·게이트 정본: `docs/MOCK_BIDDING_DESIGN.md`

⚠️ 1차 지표는 **무효율(dropout)** 이다. 낙찰률이 아니다(§0.2).
   대외 표기에 낙찰률을 쓰는 것은 전역 규칙 §4-2 위반.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.db import models
from app.db.session import get_db

router = APIRouter()


@router.get("/mock-bidding/summary")
def summary(
    bid_method: str | None = Query(None, description="세그먼트 필터 (예: 적격심사제)"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """arm 별 성적표 + G-A(채점 도달률) + 오답노트 태그 통계."""
    from app.services import mock_bidding as mb

    return {
        "arms": mb.summarize(db, bid_method=bid_method),
        "scoring_reach": mb.scoring_reach(db),
        "failure_tags": mb.failure_tag_stats(db),
        "note": "1차 지표는 dropout_rate(무효율). 대외 낙찰률 표기 금지.",
    }


@router.get("/mock-bidding/registrations")
def registrations(
    bid_no: str | None = Query(None),
    arm: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """사전 등록 원장 조회 (최신순)."""
    q = db.query(models.MockBid)
    if bid_no:
        q = q.filter(models.MockBid.bid_no == bid_no)
    if arm:
        q = q.filter(models.MockBid.arm == arm)
    if status:
        q = q.filter(models.MockBid.status == status)
    rows = q.order_by(models.MockBid.registered_at.desc()).limit(limit).all()

    return {
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "bid_no": r.bid_no,
                "arm": r.arm,
                "price": r.price,
                "bid_rate": r.bid_rate,
                "registered_at": r.registered_at.isoformat() if r.registered_at else None,
                "deadline_at": r.deadline_at.isoformat() if r.deadline_at else None,
                "strategy_version": r.strategy_version,
                "code_rev": r.code_rev,
                "snapshot": {
                    "basic_price": r.snapshot_basic_price,
                    "a_value": r.snapshot_a_value,
                    "a_value_source": r.a_value_source,
                    "lower_limit_rate": r.snapshot_lower_limit_rate,
                    "llr_source": r.llr_source,
                    "bid_method": r.snapshot_bid_method,
                    "notice_kind": r.snapshot_notice_kind,
                },
                "status": r.status,
            }
            for r in rows
        ],
    }


@router.get("/mock-bidding/results")
def results(
    outcome: str | None = Query(None, description="WIN|LOST|DROPOUT|NO_RESULT"),
    arm: str | None = Query(None),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """채점 결과 조회 (최신순). 등록 정보와 조인."""
    q = (
        db.query(models.MockBidResult, models.MockBid)
        .join(models.MockBid, models.MockBid.id == models.MockBidResult.mock_bid_id)
    )
    if outcome:
        q = q.filter(models.MockBidResult.outcome == outcome)
    if arm:
        q = q.filter(models.MockBid.arm == arm)
    rows = q.order_by(models.MockBidResult.scored_at.desc()).limit(limit).all()

    return {
        "count": len(rows),
        "items": [
            {
                "bid_no": b.bid_no,
                "arm": b.arm,
                "our_price": b.price,
                "outcome": r.outcome,
                "scoring_rev": r.scoring_rev,
                "actual_winner_price": r.actual_winner_price,
                "actual_lower_limit": r.actual_lower_limit,
                "gap_to_winner_pct": r.gap_to_winner_pct,
                "gap_to_limit_pct": r.gap_to_limit_pct,
                "ratio_error": r.ratio_error,
                "failure_tags": r.failure_tags,
                "scored_at": r.scored_at.isoformat() if r.scored_at else None,
            }
            for r, b in rows
        ],
    }
