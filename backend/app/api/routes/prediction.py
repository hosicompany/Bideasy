"""
낙찰률 예측 API 라우터
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from app.services.prediction_service import get_prediction_service

router = APIRouter(prefix="/predict", tags=["prediction"])


class PredictionRequest(BaseModel):
    """예측 요청 모델"""
    bid_type: str = Field(
        ..., 
        description="입찰 유형 (goods, service, construction)",
        example="construction"
    )
    amount: float = Field(
        ..., 
        description="예상 입찰 금액 (원)",
        example=100000000,
        gt=0
    )
    expected_participants: int = Field(
        default=10,
        description="예상 참여업체수",
        example=15,
        ge=1
    )
    target_date: Optional[str] = Field(
        default=None,
        description="목표 일자 (YYYY-MM-DD)",
        example="2026-03-01"
    )


class PredictionResponse(BaseModel):
    """예측 응답 모델"""
    predicted_rate: float = Field(description="예상 낙찰률 (%)")
    confidence: str = Field(description="신뢰도 (high/medium/low)")
    range: dict = Field(description="예상 범위")
    input: dict = Field(description="입력 데이터")
    model_metrics: dict = Field(description="모델 성능 지표")


class StatisticsResponse(BaseModel):
    """통계 응답 모델"""
    avg_rate: float
    median_rate: float
    typical_range: list


@router.post("/bid-rate", response_model=PredictionResponse)
async def predict_bid_rate(request: PredictionRequest):
    """
    낙찰률 예측
    
    입찰 유형, 금액, 참여업체수를 기반으로 예상 낙찰률을 예측합니다.
    """
    try:
        service = get_prediction_service()
        
        # 날짜 파싱
        target_date = None
        if request.target_date:
            try:
                target_date = datetime.strptime(request.target_date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요."
                )
        
        result = service.predict(
            bid_type=request.bid_type,
            amount=request.amount,
            expected_participants=request.expected_participants,
            target_date=target_date
        )
        
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"예측 중 오류 발생: {str(e)}")


@router.get("/statistics")
async def get_statistics(bid_type: Optional[str] = None):
    """
    입찰 유형별 통계 정보 조회
    
    학습 데이터 기반 평균/중앙값 낙찰률 정보를 제공합니다.
    """
    try:
        service = get_prediction_service()
        return service.get_statistics(bid_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """모델 상태 확인"""
    try:
        service = get_prediction_service()
        return {
            "status": "healthy",
            "model_loaded": service.model is not None,
            "metrics": service.metrics
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
