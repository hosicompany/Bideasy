"""
스마트 투찰 API
- 참여수 예측 (블루오션 탐지)
- 참여수 적응형 최적 투찰가 추천
- 유형별 낙찰률 예측
- 기관별 낙찰률 통계
- 발주처 인사이트 (Historical DB)
- 투찰 역검증 ("왜 떨어졌을까?")
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import date
import logging
import sqlite3 as _sqlite

from app.core.security import require_tier

logger = logging.getLogger(__name__)
router = APIRouter()


# ML 스택(numpy/joblib) 부재·모델 미탑재 시 발생하는 예외 — 500 대신 정직한 503 으로.
# (2026-07-18: 죽은 ML 서비스가 500 + 내부 에러 문자열을 노출하던 문제 수습)

_UNAVAILABLE_ERRORS = (
    ImportError,
    ModuleNotFoundError,
    FileNotFoundError,
    _sqlite.OperationalError,
    RuntimeError,
)
_UNAVAILABLE_MSG = "이 기능은 현재 준비 중이에요. 잠시 후 다시 시도해 주세요."
_GENERIC_ERROR_MSG = "요청 처리 중 오류가 발생했어요."


# ============================================================
# Request/Response Models
# ============================================================

class CompetitionPredictRequest(BaseModel):
    bid_type: str = Field(..., description="입찰 유형 (construction, goods, service)")
    estimated_amount: float = Field(..., description="추정 금액")
    agency_name: str = Field("", description="발주기관명")
    bid_date: Optional[str] = Field(None, description="입찰일 (YYYY-MM-DD)")


class SmartBidRequest(BaseModel):
    base_amount: float = Field(..., description="기초금액")
    bid_type: str = Field("construction", description="입찰 유형")
    a_value: float = Field(0, description="A값 (시설공사)")
    estimated_amount: Optional[float] = Field(None, description="추정가격")
    agency_name: str = Field("", description="발주기관명")
    agency_type: str = Field("national", description="발주기관 유형 (national, local, public_corp)")
    bid_date: Optional[str] = Field(None, description="입찰일 (YYYY-MM-DD)")
    margin_pct: Optional[float] = Field(None, description="수동 마진 (None이면 자동)")


class BidRatePredictRequest(BaseModel):
    bid_type: str = Field(..., description="입찰 유형")
    estimated_amount: float = Field(..., description="추정 금액")
    expected_participants: int = Field(10, description="예상 참여업체수")
    agency_name: str = Field("", description="발주기관명")
    bid_date: Optional[str] = Field(None, description="입찰일")


class BidVerifyRequest(BaseModel):
    bid_no: str = Field(..., description="공고번호")
    my_bid_price: float = Field(..., description="내 투찰가")
    basic_price: float = Field(..., description="기초금액")
    organization: str = Field("", description="발주기관명")


# ============================================================
# 1. 참여수 예측 (블루오션 탐지)
# ============================================================

@router.post("/competition/predict")
async def predict_competition(req: CompetitionPredictRequest, _user=Depends(require_tier("pro"))) -> Dict[str, Any]:
    """
    입찰 참여업체수 예측 및 블루오션 판별

    - 예상 참여업체수, 경쟁 강도, 블루오션 확률 반환
    - 기관별 과거 통계 포함
    """
    try:
        from app.services.participant_prediction_service import get_participant_prediction_service
        service = get_participant_prediction_service()

        bid_date = date.fromisoformat(req.bid_date) if req.bid_date else date.today()

        result = service.predict(
            bid_type=req.bid_type,
            estimated_amount=req.estimated_amount,
            agency_name=req.agency_name,
            bid_date=bid_date,
        )
        return {"status": "success", "data": result}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="참여수 예측 기능은 현재 준비 중이에요.")
    except Exception:
        logger.exception("참여수 예측 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


# ============================================================
# 2. 스마트 투찰 추천 (참여수 적응형)
# ============================================================

@router.post("/recommend")
async def get_smart_recommendation(req: SmartBidRequest, _user=Depends(require_tier("pro_plus"))) -> Dict[str, Any]:
    """
    안전 투찰가 추천 (autocalibrate 룰기반)

    2026-07-18: 죽은 ML 시뮬레이션(numpy 의존, 생산 500)을 검증된 자가보정
    룰기반(`recommend_bid_price`, 순수 Python)으로 대체. 낙찰가를 예측하지 않고,
    과거 개찰 데이터로 보정한 "무효·적자를 피하는 안전선"을 제시한다.
    검증 표본이 공사(적격심사)에 한정되므로 물품·용역은 미지원(503).
    """
    bid_type = (req.bid_type or "construction").lower()
    if bid_type != "construction":
        raise HTTPException(
            status_code=503,
            detail="안전 투찰 추천은 현재 공사 공고만 지원해요. 물품·용역은 준비 중이에요.",
        )

    try:
        from app.services.calculator import CalculatorService

        rec = CalculatorService.recommend_bid_price(
            basic_price=req.base_amount,
            bid_method="DEFAULT",
            contract_type="CONSTRUCTION",
            a_value=req.a_value or 0,
        )

        lower_rate = rec["lower_limit_rate"]          # 예: 89.745 (%)
        adjustment = rec["adjustment"]
        margin = rec["margin"]
        predicted_reserved = req.base_amount * (1 + adjustment / 100.0)
        # 실제 하한선(예상 예정가 기준) — 이 밑으로 쓰면 무효
        danger_zone = predicted_reserved * lower_rate / 100.0

        data = {
            "optimal_bid": float(rec["recommended_price"]),
            "lower_limit": round(lower_rate / 100.0, 5),
            "lower_limit_pct": f"{lower_rate:.3f}%",
            "applied_margin_pct": margin,
            "effective_rate": rec["target_rate_pct"],
            "expected_planned_price": {
                "mean": round(predicted_reserved),
                "range": {
                    "low": round(predicted_reserved * 0.97),   # 예정가 규정 변동 ±3%
                    "high": round(predicted_reserved * 1.03),
                },
            },
            "bid_rate": {"at_mean": rec["bid_rate"]},
            "tie_risk": "high" if margin <= 0.05 else "medium",
            "danger_zone": round(danger_zone),
            "recommendation": (
                f"과거 개찰 데이터로 보정한 규칙 기반 안전선이에요. "
                f"기초금액의 {rec['bid_rate']:.2f}% 지점은 낙찰하한선({lower_rate:.3f}%) 위라 "
                f"무효·적자 위험이 낮은 구간이에요. 낙찰가를 예측하는 게 아니라, "
                f"'잃지 않는 선'을 알려드리는 거예요."
            ),
            "competition": None,        # 참여수 예측 ML 미탑재 — 정직하게 생략
            "basis": "autocalibrate_rule_based",
            "input": {
                "base_amount": req.base_amount,
                "a_value": req.a_value,
                "bid_type": bid_type,
            },
        }
        return {"status": "success", "data": data}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_MSG)
    except Exception:
        logger.exception("스마트 투찰 추천 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


# ============================================================
# 3. 유형별 낙찰률 예측
# ============================================================

@router.post("/rate/predict")
async def predict_bid_rate(req: BidRatePredictRequest, _user=Depends(require_tier("pro_plus"))) -> Dict[str, Any]:
    """
    유형별 낙찰률 예측

    - 물품/용역: ML 모델 기반 예측 (분산이 커서 효과적)
    - 공사: 참여수 기반 전략이 우선이므로 참고용
    """
    try:
        from app.services.bidrate_prediction_service import get_bidrate_prediction_service
        service = get_bidrate_prediction_service()

        bid_date = date.fromisoformat(req.bid_date) if req.bid_date else date.today()

        result = service.predict_bid_rate(
            bid_type=req.bid_type,
            estimated_amount=req.estimated_amount,
            expected_participants=req.expected_participants,
            agency_name=req.agency_name,
            bid_date=bid_date,
        )
        return {"status": "success", "data": result}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="낙찰률 예측 기능은 현재 준비 중이에요.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("낙찰률 예측 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


# ============================================================
# 4. 기관별 낙찰률 통계
# ============================================================

@router.get("/agency/stats")
async def get_agency_bid_stats(
    bid_type: str = Query(..., description="입찰 유형"),
    agency_name: str = Query("", description="기관명 (정확 매칭)"),
    keyword: str = Query("", description="기관명 검색어"),
    limit: int = Query(20, description="결과 수", ge=1, le=100),
) -> Dict[str, Any]:
    """
    기관별 과거 낙찰률 통계

    - 평균/중앙값 낙찰률, 표준편차, 평균 참여수, 총 입찰 건수
    - 키워드 검색 지원
    """
    try:
        from app.services.bidrate_prediction_service import get_bidrate_prediction_service
        service = get_bidrate_prediction_service()

        result = service.get_agency_statistics(
            bid_type=bid_type,
            agency_name=agency_name,
            keyword=keyword,
            limit=limit,
        )
        return {"status": "success", "data": result}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="기관 통계 기능은 현재 준비 중이에요.")
    except Exception:
        logger.exception("기관 통계 조회 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


@router.get("/agency/search")
async def search_agencies(
    keyword: str = Query(..., description="기관명 검색어", min_length=1),
    limit: int = Query(10, description="결과 수", ge=1, le=50),
) -> Dict[str, Any]:
    """기관명 검색 (참여수 예측용)"""
    try:
        from app.services.participant_prediction_service import get_participant_prediction_service
        service = get_participant_prediction_service()

        results = service.search_agencies(keyword=keyword, limit=limit)
        return {"status": "success", "data": results}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="기관 검색 기능은 현재 준비 중이에요.")
    except Exception:
        logger.exception("기관 검색 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


@router.get("/agency/insights")
async def get_agency_insights_endpoint(
    agency_name: str = Query(..., description="발주기관명"),
    bid_type: str = Query(None, description="입찰 유형 (construction, goods, service)"),
) -> Dict[str, Any]:
    """
    발주처 인사이트 — Historical DB 직접 조회

    - 평균/중앙값 낙찰률, 참여업체 수, 최근 트렌드
    - 전체 평균 대비 비교 + 한줄 인사이트
    """
    try:
        from app.services.organization_insights import get_agency_insights

        result = get_agency_insights(agency_name, bid_type)
        return {"status": "success", "data": result}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="발주처 인사이트 기능은 현재 준비 중이에요.")
    except Exception:
        logger.exception("발주처 인사이트 조회 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


# ============================================================
# 6. 투찰 역검증 ("왜 떨어졌을까?")
# ============================================================

@router.post("/verify")
async def verify_bid_result(req: BidVerifyRequest, _user=Depends(require_tier("pro"))) -> Dict[str, Any]:
    """
    투찰 역검증 — 내 투찰가를 입력하면 순위/편차/개선점 분석

    - 개찰 결과에서 해당 공고의 낙찰 데이터 조회
    - 사용자 투찰가 대비 순위, 편차, 한줄 분석
    """
    try:
        from app.services.bid_verifier import verify_bid

        result = verify_bid(
            bid_no=req.bid_no,
            my_bid_price=req.my_bid_price,
            basic_price=req.basic_price,
            organization=req.organization,
        )
        return {"status": "success", "data": result}

    except _UNAVAILABLE_ERRORS:
        raise HTTPException(status_code=503, detail="투찰 역검증 기능은 현재 준비 중이에요.")
    except Exception:
        logger.exception("투찰 역검증 실패")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR_MSG)


@router.get("/summary")
async def get_model_summary() -> Dict[str, Any]:
    """전체 모델 상태 요약"""
    summary = {}

    try:
        from app.services.participant_prediction_service import get_participant_prediction_service
        svc = get_participant_prediction_service()
        summary["participant_model"] = {
            "status": "ready",
            "accuracy": svc.metrics.get("classification", {}).get("accuracy", 0),
            "blue_ocean_accuracy": svc.metrics.get("classification", {}).get("binary_accuracy", 0),
        }
    except Exception as e:
        summary["participant_model"] = {"status": "unavailable", "error": str(e)}

    try:
        from app.services.bidrate_prediction_service import get_bidrate_prediction_service
        svc = get_bidrate_prediction_service()
        summary["bidrate_model"] = {
            "status": "ready",
            "types": svc.get_all_type_summary(),
        }
    except Exception as e:
        summary["bidrate_model"] = {"status": "unavailable", "error": str(e)}

    return {"status": "success", "data": summary}
