"""
스마트 투찰 API
- 참여수 예측 (블루오션 탐지)
- 참여수 적응형 최적 투찰가 추천
- 유형별 낙찰률 예측
- 기관별 낙찰률 통계
- 발주처 인사이트 (Historical DB)
- 투찰 역검증 ("왜 떨어졌을까?")
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import date
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


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
async def predict_competition(req: CompetitionPredictRequest) -> Dict[str, Any]:
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

    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="참여수 예측 모델이 아직 준비되지 않았습니다.")
    except Exception as e:
        logger.error(f"참여수 예측 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 2. 스마트 투찰 추천 (참여수 적응형)
# ============================================================

@router.post("/recommend")
async def get_smart_recommendation(req: SmartBidRequest) -> Dict[str, Any]:
    """
    참여수 적응형 최적 투찰가 추천

    - 참여수 예측 → 동적 마진 결정 → 최적 투찰가 계산
    - margin_pct를 직접 지정하면 수동 모드
    """
    try:
        from app.services.simulation_service import (
            get_simulation_service, AgencyType
        )
        service = get_simulation_service()

        bid_date = date.fromisoformat(req.bid_date) if req.bid_date else date.today()

        agency_type_map = {
            "national": AgencyType.NATIONAL,
            "local": AgencyType.LOCAL,
            "public_corp": AgencyType.PUBLIC_CORP,
        }
        agency_type = agency_type_map.get(req.agency_type, AgencyType.NATIONAL)

        result = service.calculate_optimal_bid(
            base_amount=req.base_amount,
            a_value=req.a_value,
            bid_type=req.bid_type,
            estimated_amount=req.estimated_amount,
            bid_date=bid_date,
            agency_type=agency_type,
            margin_pct=req.margin_pct,
            agency_name=req.agency_name,
        )
        return {"status": "success", "data": result}

    except Exception as e:
        logger.error(f"스마트 투찰 추천 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 3. 유형별 낙찰률 예측
# ============================================================

@router.post("/rate/predict")
async def predict_bid_rate(req: BidRatePredictRequest) -> Dict[str, Any]:
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

    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="낙찰률 예측 모델이 아직 준비되지 않았습니다.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"낙찰률 예측 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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

    except Exception as e:
        logger.error(f"기관 통계 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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

    except Exception as e:
        logger.error(f"기관 검색 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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

    except Exception as e:
        logger.error(f"발주처 인사이트 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 6. 투찰 역검증 ("왜 떨어졌을까?")
# ============================================================

@router.post("/verify")
async def verify_bid_result(req: BidVerifyRequest) -> Dict[str, Any]:
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

    except Exception as e:
        logger.error(f"투찰 역검증 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
