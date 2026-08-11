"""관리자 — 모의투찰(Shadow Bidding) 조회.

설계·게이트 정본: `docs/MOCK_BIDDING_DESIGN.md`

⚠️ 1차 지표는 **무효율(dropout)** 이다. 낙찰률이 아니다(§0.2).
   대외 표기에 낙찰률을 쓰는 것은 전역 규칙 §4-2 위반.
"""
from typing import Literal

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
    """arm 별 성적표 + G-A/G-B/G-C + 오답노트 태그 통계."""
    from app.services import mock_bidding as mb

    gates = mb.evaluate_gates(db)
    return {
        "arms": mb.summarize(db, bid_method=bid_method),
        "scoring_reach": gates["g_a"],
        "gates": gates,
        "queue_health": mb.score_queue_health(db),
        "sample_validity": mb.sample_validity(db, bid_method=bid_method),
        "failure_tags": mb.failure_tag_stats(db),
        "note": (
            "성능 지표는 기초금액 일관성 검사를 통과한 표본만 사용. "
            "1차 지표는 dropout_rate(무효율). 대외 낙찰률 표기 금지."
        ),
    }


@router.get("/mock-bidding/charts")
def charts(
    arm: str = Query("active", description="추이·세그먼트 기준 arm (기본 active = 운영 정본)"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """시각화 대시보드용 집계 — 전부 등록 건당 최신 scoring_rev 기준.

    화면 순서는 §0.2 지표 우선순위(무효율 → 적중률 → 등수 → 격차 → 오차)를
    따르고, 그 배치는 admin.js 가 책임진다. 여기는 데이터만 만든다.
    """
    from app.services import mock_bidding as mb

    gates = mb.evaluate_gates(db)
    return {
        "arms": mb.summarize(db),
        "scoring_reach": gates["g_a"],
        "gates": gates,
        "queue_health": mb.score_queue_health(db),
        "sample_validity": mb.sample_validity(db),
        "rank_distribution": mb.rank_distribution(db),
        "rank_histogram_cap": mb.RANK_HISTOGRAM_CAP,
        # 등수 축이 개찰 API 와 여전히 같은지 — 어긋나면 등수 해석을 멈춘다(§9)
        "rank_axis_health": mb.rank_axis_health(db),
        "gap_distribution": mb.gap_distribution(db),
        "gap_buckets": list(mb.GAP_BUCKETS),
        "ratio_error_trend": mb.ratio_error_trend(db, arm=arm),
        "failure_tags": mb.failure_tag_stats(db),
        "segments": mb.segment_stats(db, arm=arm),
        "trend_arm": arm,
        "note": (
            "성능 지표는 기초금액 일관성 검사를 통과한 표본만 사용. "
            "1차 지표는 dropout_rate(무효율). 대외 낙찰률 표기 금지."
        ),
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


@router.get("/mock-bidding/history")
def history(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    state: Literal["all", "completed", "waiting"] = Query(
        "completed", description="개찰 완료·결과 대기 필터"
    ),
    search: str | None = Query(None, max_length=100, description="공고번호 일부 검색"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """공고 단위 전체 이력 — 5개 arm 과 최신 채점 결과를 한 묶음으로 반환."""
    from app.services import mock_bidding as mb

    return mb.history_page(
        db,
        page=page,
        page_size=page_size,
        state=state,
        search=search,
    )


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
                "estimated_rank": r.estimated_rank,
                "participants_count": r.participants_count,
                # 등수의 분모. 이걸 빼면 CSV 로 뽑아 백분위를 낼 때 분모가
                # 2배(무효 47.6% 포함)가 되어 오독이 재생산된다.
                "valid_participants_count": r.valid_participants_count,
                "gap_to_winner_pct": r.gap_to_winner_pct,
                "gap_to_limit_pct": r.gap_to_limit_pct,
                "ratio_error": r.ratio_error,
                "failure_tags": r.failure_tags,
                "scored_at": r.scored_at.isoformat() if r.scored_at else None,
            }
            for r, b in rows
        ],
    }
