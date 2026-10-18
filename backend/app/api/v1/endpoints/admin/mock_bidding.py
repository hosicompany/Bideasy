"""관리자 — 모의투찰(Shadow Bidding) 조회.

설계·게이트 정본: `docs/MOCK_BIDDING_DESIGN.md`

⚠️ 1차 지표는 **무효율(dropout)** 이다. 낙찰률이 아니다(§0.2).
   대외 표기에 낙찰률을 쓰는 것은 전역 규칙 §4-2 위반.
"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_
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
        # 등수 분포에서 빠진 수(사유별) — 숨기면 전수를 본 것처럼 읽힌다
        "rank_excluded": mb.rank_distribution_excluded(db),
        "rank_histogram_cap": mb.RANK_HISTOGRAM_CAP,
        # 등수 축이 개찰 API 와 여전히 같은지 — 어긋나면 등수 해석을 멈춘다(§9)
        "rank_axis_health": mb.rank_axis_health(db),
        "gap_distribution": mb.gap_distribution(db),
        "gap_buckets": list(mb.GAP_BUCKETS),
        "ratio_error_trend": mb.ratio_error_trend(db, arm=arm),
        "ratio_error_segments": mb.ratio_error_segment_report(db, arm=arm),
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


def _history_filters(
    state: Literal["all", "completed", "waiting"] = Query(
        "completed", description="개찰 완료·결과 대기 필터"
    ),
    search: str | None = Query(None, max_length=100, description="공고번호 일부 검색"),
    arm: Literal["standard", "active", "frontier_c5", "frontier_c10", "aggressive"] = Query(
        "active", description="판정·순위·주의 요소·낙찰가 차이 필터를 적용할 가격안"
    ),
    date_field: Literal["deadline", "opened"] = Query(
        "deadline", description="기간 기준일 — 마감일(기본) 또는 개찰일"
    ),
    date_from: date | None = Query(None, description="기간 시작일(포함, KST)"),
    date_to: date | None = Query(None, description="기간 종료일(포함, KST)"),
    outcome: Literal["WIN", "LOST", "DROPOUT"] | None = Query(
        None, description="판정 필터"
    ),
    rank_min: int | None = Query(None, ge=1, description="가상 순위 하한(포함)"),
    rank_max: int | None = Query(None, ge=1, description="가상 순위 상한(포함)"),
    rank_pct_max: float | None = Query(
        None, gt=0, le=100, description="유효 투찰 대비 상위 % 이내"
    ),
    bid_method: str | None = Query(None, max_length=100, description="입찰방법(스냅샷) 일치"),
    bracket: Literal["small", "medium", "large", "xlarge", "xxlarge"] | None = Query(
        None, description="기초금액 금액대"
    ),
    tag: str | None = Query(None, max_length=50, description="오답노트 주의 요소"),
    gap_bucket: str | None = Query(
        None, max_length=20, description="낙찰가 대비 차이 구간(차트 GAP_BUCKETS 와 동일)"
    ),
    valid_base_only: bool = Query(False, description="기초금액 일관성 통과 표본만"),
    sort: Literal["deadline_desc", "deadline_asc", "rank_asc", "gap_abs_asc"] = Query(
        "deadline_desc", description="정렬 — rank_asc 는 등수 축 검증 후에만"
    ),
) -> dict:
    """목록과 CSV 가 같은 필터 계약을 쓰도록 한 곳에서 받는다."""
    return {
        "state": state, "search": search, "arm": arm, "date_field": date_field,
        "date_from": date_from, "date_to": date_to, "outcome": outcome,
        "rank_min": rank_min, "rank_max": rank_max, "rank_pct_max": rank_pct_max,
        "bid_method": bid_method or None, "bracket": bracket, "tag": tag or None,
        "gap_bucket": gap_bucket or None, "valid_base_only": valid_base_only,
        "sort": sort,
    }


def _filter_errors(fn):
    """서비스 필터 오류 → HTTP. 순위 잠금은 409, 나머지 잘못된 조합은 422."""
    from app.services import mock_bidding as mb

    try:
        return fn()
    except mb.RankFilterLocked:
        raise HTTPException(
            status_code=409,
            detail="등수 축 검증이 끝나기 전에는 순위로 거르거나 정렬할 수 없어요.",
        )
    except mb.HistoryFilterError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/mock-bidding/history")
def history(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    filters: dict = Depends(_history_filters),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """공고 단위 전체 이력 — 5개 arm 과 최신 채점 결과를 한 묶음으로 반환.

    순위 필터·순위 정렬은 등수 축 검증이 통과했을 때만 받는다(409). 화면이
    등수를 숨기는 동안 순위로 거른 목록이 등수를 대신 드러내지 않게 하기 위함이다.
    """
    from app.services import mock_bidding as mb

    return _filter_errors(lambda: mb.history_page(
        db, page=page, page_size=page_size, **filters))


@router.get("/mock-bidding/history/facets")
def history_facets(
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """이력 필터 선택지(입찰방법·금액대·주의 요소·낙찰가 차이 구간·정렬)."""
    from app.services import mock_bidding as mb

    return mb.history_facets(db)


#: 스프레드시트가 수식으로 해석하는 첫 글자 — 공고명 등 외부 문자열 칸에만 막는다
_CSV_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")
_CSV_TEXT_COLUMNS = {"title", "organization", "bid_method", "failure_tags", "bid_no"}


def _csv_cell(key: str, value):
    if value is None:
        return ""
    if key in _CSV_TEXT_COLUMNS and isinstance(value, str) \
            and value.startswith(_CSV_FORMULA_PREFIX):
        return "'" + value
    return value


@router.get("/mock-bidding/history.csv")
def history_csv(
    filters: dict = Depends(_history_filters),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """화면 목록과 같은 조건의 CSV — 공고 × 가격안 1행, 최대 5,000공고.

    가상 순위 칸은 등수 축 검증이 통과했을 때만 채운다(화면과 같은 fail-closed).
    """
    import csv
    import io

    from fastapi.responses import Response

    from app.services import mock_bidding as mb

    healthy = mb.rank_axis_health(db).get("healthy") is True
    data = _filter_errors(lambda: mb.history_export_rows(
        db, rank_verified=healthy, **filters))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in mb.HISTORY_CSV_COLUMNS])
    for row in data["rows"]:
        writer.writerow([_csv_cell(key, row.get(key)) for key, _ in mb.HISTORY_CSV_COLUMNS])
    stamp = mb.now_kst().strftime("%Y%m%d-%H%M")
    return Response(
        # BOM — 엑셀이 UTF-8 한글을 깨뜨리지 않게
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="mock-bidding-history-{stamp}.csv"',
            "X-Total-Notices": str(data["total_notices"]),
            "X-Exported-Notices": str(data["exported_notices"]),
            "X-Truncated": "1" if data["truncated"] else "0",
            "X-Rank-Included": "1" if data["rank_included"] else "0",
        },
    )


@router.get("/mock-bidding/results")
def results(
    outcome: str | None = Query(None, description="WIN|LOST|DROPOUT|NO_RESULT"),
    arm: str | None = Query(None),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """채점 결과 조회 (최신순). 등록 정보와 조인. **등록 건당 최신 rev 만.**

    최신 rev 로 좁히지 않으면 재채점·등수 백필이 rev 를 쌓을 때마다 같은
    (공고, arm) 이 여러 줄로 나온다. `scored_at` 은 원 측정 시각을 보존하므로
    정렬로도 갈라지지 않아, 이걸 CSV 로 뽑으면 구 rev 가 섞인 채 집계된다.
    """
    from app.services import mock_bidding as mb

    sq = mb.latest_rev_subquery(db)
    q = (
        db.query(models.MockBidResult, models.MockBid)
        .join(models.MockBid, models.MockBid.id == models.MockBidResult.mock_bid_id)
        .join(sq, and_(models.MockBidResult.mock_bid_id == sq.c.mock_bid_id,
                       models.MockBidResult.scoring_rev == sq.c.max_rev))
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
