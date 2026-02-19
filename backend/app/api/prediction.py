"""
낙찰가 예측 API 엔드포인트
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum

from app.services.prediction_service import (
    get_prediction_service,
    BidType,
    PredictionResult,
)

router = APIRouter(prefix="/prediction", tags=["예측"])


class BidTypeEnum(str, Enum):
    """입찰 유형"""
    goods = "goods"
    service = "service"
    construction = "construction"
    foreign = "foreign"


class PredictionRequest(BaseModel):
    """예측 요청"""
    base_price: int = Field(..., description="기초금액 (원)", ge=1)
    bid_type: BidTypeEnum = Field(default=BidTypeEnum.goods, description="입찰 유형")
    organization: Optional[str] = Field(None, description="발주기관 (Phase 2)")
    region: Optional[str] = Field(None, description="지역 (Phase 2)")
    category: Optional[str] = Field(None, description="세부 업종 (Phase 2)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "base_price": 100000000,
                "bid_type": "goods",
            }
        }


class PredictionResponse(BaseModel):
    """예측 응답"""
    # 예측 구간
    min_rate: float = Field(..., description="최소 사정률 (%)")
    max_rate: float = Field(..., description="최대 사정률 (%)")
    recommended_rate: float = Field(..., description="추천 사정률 (%)")
    
    # 예측 금액
    min_price: int = Field(..., description="최소 예측가 (원)")
    max_price: int = Field(..., description="최대 예측가 (원)")
    recommended_price: int = Field(..., description="추천 투찰가 (원)")
    
    # 신뢰도
    confidence: float = Field(..., description="신뢰도 (0~1)")
    confidence_level: str = Field(..., description="신뢰 수준")
    
    # 분석 근거
    analysis_basis: List[str] = Field(..., description="분석 근거")
    similar_cases: int = Field(..., description="유사 사례 수")
    
    # 메타
    model_version: str = Field(..., description="모델 버전")
    predicted_at: str = Field(..., description="예측 시각")
    
    # 면책 조항
    disclaimer: str = Field(
        default="본 예측은 과거 데이터 기반 통계 분석 결과이며, 참고용으로만 사용하시기 바랍니다. 실제 낙찰 결과와 차이가 있을 수 있습니다.",
        description="면책 조항"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "min_rate": 85.5,
                "max_rate": 88.5,
                "recommended_rate": 87.0,
                "min_price": 85500000,
                "max_price": 88500000,
                "recommended_price": 87000000,
                "confidence": 0.75,
                "confidence_level": "높음",
                "analysis_basis": [
                    "금액대: 1억 ~ 10억",
                    "과거 523건 데이터 기반 분석",
                    "평균 사정률: 87.2%",
                ],
                "similar_cases": 523,
                "model_version": "v1.0-stats",
                "predicted_at": "2026-02-07T22:30:00",
                "disclaimer": "본 예측은 참고용입니다.",
            }
        }


@router.post("/", response_model=PredictionResponse)
async def predict_winning_price(request: PredictionRequest):
    """
    낙찰가 예측
    
    기초금액과 입찰 유형을 기반으로 예상 낙찰가 구간을 예측합니다.
    
    - **base_price**: 기초금액 (필수)
    - **bid_type**: 입찰 유형 (goods/service/construction/foreign)
    
    반환값:
    - 예측 사정률 구간 (min_rate ~ max_rate)
    - 추천 투찰가
    - 신뢰도 및 분석 근거
    """
    service = get_prediction_service()
    
    # 예측 수행
    result = service.predict(
        base_price=request.base_price,
        bid_type=BidType(request.bid_type.value),
        organization=request.organization,
        region=request.region,
        category=request.category,
    )
    
    return PredictionResponse(
        min_rate=result.min_rate,
        max_rate=result.max_rate,
        recommended_rate=result.recommended_rate,
        min_price=result.min_price,
        max_price=result.max_price,
        recommended_price=result.recommended_price,
        confidence=result.confidence,
        confidence_level=result.confidence_level,
        analysis_basis=result.analysis_basis,
        similar_cases=result.similar_cases,
        model_version=result.model_version,
        predicted_at=result.predicted_at,
    )


@router.get("/quick")
async def quick_predict(
    base_price: int = Query(..., description="기초금액", ge=1),
    bid_type: BidTypeEnum = Query(default=BidTypeEnum.goods, description="입찰 유형"),
):
    """
    빠른 예측 (GET 방식)
    
    간단한 URL 파라미터로 예측 결과를 조회합니다.
    """
    service = get_prediction_service()
    
    result = service.predict(
        base_price=base_price,
        bid_type=BidType(bid_type.value),
    )
    
    return {
        "base_price": base_price,
        "bid_type": bid_type.value,
        "prediction": {
            "rate_range": f"{result.min_rate}% ~ {result.max_rate}%",
            "recommended_rate": f"{result.recommended_rate}%",
            "recommended_price": result.recommended_price,
            "confidence": result.confidence_level,
        },
        "disclaimer": "참고용 예측입니다.",
    }


class BacktestRequest(BaseModel):
    """백테스트 요청"""
    bid_type: BidTypeEnum = Field(default=BidTypeEnum.goods)
    # 실제로는 테스트 데이터를 받거나 DB에서 조회


class BacktestResponse(BaseModel):
    """백테스트 결과"""
    total_cases: int
    hit_rate: float
    avg_error: float
    status: str


@router.post("/backtest", response_model=BacktestResponse)
async def run_backtest(request: BacktestRequest):
    """
    백테스트 실행
    
    과거 데이터를 기반으로 예측 모델의 정확도를 검증합니다.
    (현재는 데이터 수집 중으로 제한적 결과)
    """
    service = get_prediction_service()
    
    # 임시 테스트 데이터 (실제로는 DB에서 조회)
    test_data = [
        {"base_price": 100000000, "actual_winning_rate": 87.5},
        {"base_price": 50000000, "actual_winning_rate": 88.2},
        {"base_price": 200000000, "actual_winning_rate": 86.8},
    ]
    
    result = service.backtest(test_data, BidType(request.bid_type.value))
    
    return BacktestResponse(
        total_cases=result["total"],
        hit_rate=result["hit_rate"],
        avg_error=result["avg_error"],
        status="데이터 수집 중 - 제한적 결과",
    )


@router.get("/status")
async def get_prediction_status():
    """
    예측 서비스 상태
    
    현재 예측 모델의 상태와 데이터 수집 현황을 반환합니다.
    """
    service = get_prediction_service()
    
    return {
        "model_version": "v1.0-stats",
        "phase": "MVP (Phase 1)",
        "data_status": {
            "historical_data_count": len(service.historical_data),
            "cache_categories": len(service._rate_cache),
        },
        "features": {
            "statistical_prediction": True,
            "ontology_analysis": False,  # Phase 2
            "ml_model": False,  # Phase 2
            "organization_patterns": False,  # Phase 2
        },
        "next_update": "데이터 수집 후 모델 업데이트 예정",
    }
