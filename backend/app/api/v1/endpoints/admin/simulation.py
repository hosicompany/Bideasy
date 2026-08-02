"""관리자 — 모의 투찰 백테스트 시뮬레이션 (Phase E).

기존 autocalibrate 자산 재사용:
- dataset.load_records() — 과거 개찰결과(2021~)
- optimizer.evaluate_params(records, params) — 종합 지표 (1-pass, 고속)
동기 실행 (evaluate_params 가 단일 루프라 빠름). 데이터 없으면 친절히 안내.
"""
import copy

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import require_admin
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()

_BRACKETS = ["small", "medium", "large", "xlarge", "xxlarge"]


def _load_records(db=None):
    """정적 과거 파일 + (db 제공 시) 누적 opening_results 병합."""
    from app.services.autocalibrate.dataset import load_records
    return load_records(db=db)


def _active_params():
    from app.services.autocalibrate.strategy_store import get_default_store
    return get_default_store().load_active().params


def _filter(records, year_from, year_to, bid_method):
    out = records
    if year_from:
        out = [r for r in out if r.year >= int(year_from)]
    if year_to:
        out = [r for r in out if r.year <= int(year_to)]
    if bid_method:
        out = [r for r in out if r.bid_method == bid_method]
    return out


@router.get("/simulation/datasets")
def datasets(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """백테스트 가능한 데이터셋 현황 (정적 + 누적 DB, 연도별 건수)."""
    try:
        records = _load_records(db)
    except Exception as e:
        return {"available": False, "error": str(e), "by_year": {}, "total": 0, "methods": []}
    by_year, methods = {}, set()
    for r in records:
        by_year[r.year] = by_year.get(r.year, 0) + 1
        if r.bid_method:
            methods.add(r.bid_method)
    return {
        "available": len(records) > 0,
        "total": len(records),
        "by_year": dict(sorted(by_year.items())),
        "methods": sorted(methods),
    }


@router.post("/simulation/backtest")
def run_backtest(body: dict = Body(default={}), db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """현재(또는 override) 전략으로 백테스트 → 종합 + 가격대별 지표."""
    from app.services.autocalibrate.optimizer import evaluate_params

    try:
        records = _load_records(db)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"백테스트 데이터를 불러올 수 없어요: {e}")
    records = _filter(records, body.get("year_from"), body.get("year_to"), body.get("bid_method"))
    if not records:
        return {"metrics": {}, "by_bracket": [], "sample": 0, "message": "조건에 맞는 데이터가 없어요."}

    try:
        params = body.get("strategy") or _active_params()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"활성 전략을 불러올 수 없어요: {e}")

    overall = evaluate_params(records, params)
    by_bracket = []
    for b in _BRACKETS:
        subset = [r for r in records if r.bracket == b]
        if subset:
            m = evaluate_params(subset, params)
            by_bracket.append({"bracket": b, **m})
    return {"metrics": overall, "by_bracket": by_bracket, "sample": len(records)}


@router.post("/simulation/whatif")
def whatif(body: dict = Body(default={}), db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """여유분(margin) 전역 가산값을 범위로 변화시키며 지표 변화 관찰.

    body: { year_from?, year_to?, bid_method?, margin_deltas?: [..%p..] }
    각 delta 를 모든 세그먼트의 margin 에 더해 evaluate. (간이 민감도 분석)
    """
    from app.services.autocalibrate.optimizer import evaluate_params

    try:
        records = _filter(_load_records(db), body.get("year_from"), body.get("year_to"), body.get("bid_method"))
        base = _active_params()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"데이터/전략 로드 실패: {e}")
    if not records:
        return {"results": [], "message": "조건에 맞는 데이터가 없어요."}

    deltas = body.get("margin_deltas") or [-0.4, -0.2, 0.0, 0.2, 0.4, 0.6]
    results = []
    for d in deltas:
        params = copy.deepcopy(base)
        for method, brackets in params.items():
            for bk, pair in brackets.items():
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    brackets[bk] = [pair[0], round(float(pair[1]) + float(d), 3)]
        m = evaluate_params(records, params)
        results.append({"margin_delta": d, **m})
    return {"results": results, "sample": len(records)}

@router.get("/simulation/arms")
def arm_backtest(
    bid_method: str | None = Query(None, description="세그먼트 필터 (예: 적격심사제)"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """과거 데이터에 모의투찰과 **같은 5 arm** 을 적용한 비교표.

    모의투찰(전향 실험)은 표본이 쌓이는 데 시간이 걸리므로, 같은 arm 구성으로
    과거를 재평가해 지금 당장 방향을 본다. 판정은 mock_bidding.judge 를
    재사용하므로 모의투찰 화면과 정의가 갈라지지 않는다.

    ⚠️ 응답의 `caveats` 를 화면에 반드시 함께 표기할 것 — 백테스트는 사후
    재구성이라 파라미터가 바뀌면 과거 수치도 변한다(증거가 아니라 참고).
    """
    from app.services import arm_backtest as ab

    try:
        return ab.run(db=db, bid_method=bid_method)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[admin.simulation.arms] {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"5-arm 백테스트를 실행할 수 없어요: {e}")
