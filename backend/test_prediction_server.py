"""
예측 기능 테스트용 간단 서버
"""
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
from typing import List
from enum import Enum
import uvicorn

# 직접 import
import sys
sys.path.insert(0, '.')
from app.services.prediction_service import get_prediction_service, BidType

app = FastAPI(title="BidEasy Prediction API Test", version="1.0")


class BidTypeEnum(str, Enum):
    goods = "goods"
    service = "service"
    construction = "construction"


class PredictionRequest(BaseModel):
    base_price: int = Field(..., description="기초금액", ge=1)
    bid_type: BidTypeEnum = Field(default=BidTypeEnum.goods)


class PredictionResponse(BaseModel):
    min_rate: float
    max_rate: float
    recommended_rate: float
    min_price: int
    max_price: int
    recommended_price: int
    confidence: float
    confidence_level: str
    analysis_basis: List[str]
    disclaimer: str = "본 예측은 참고용입니다."


@app.get("/")
def root():
    return {"message": "BidEasy Prediction API - Test Server"}


@app.post("/predict", response_model=PredictionResponse)
def predict(request: PredictionRequest):
    """낙찰가 예측"""
    service = get_prediction_service()
    
    result = service.predict(
        base_price=request.base_price,
        bid_type=BidType(request.bid_type.value)
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
    )


@app.get("/predict/quick")
def quick_predict(
    base_price: int = Query(..., description="기초금액", ge=1),
    bid_type: BidTypeEnum = Query(default=BidTypeEnum.goods)
):
    """빠른 예측 (GET)"""
    service = get_prediction_service()
    
    result = service.predict(
        base_price=base_price,
        bid_type=BidType(bid_type.value)
    )
    
    return {
        "input": {
            "base_price": f"{base_price:,}원",
            "bid_type": bid_type.value
        },
        "prediction": {
            "rate_range": f"{result.min_rate}% ~ {result.max_rate}%",
            "recommended_rate": f"{result.recommended_rate}%",
            "recommended_price": f"{result.recommended_price:,}원",
            "confidence": result.confidence_level
        },
        "basis": result.analysis_basis
    }


if __name__ == "__main__":
    print("Starting BidEasy Prediction Test Server...")
    print("API Docs: http://localhost:8001/docs")
    uvicorn.run(app, host="0.0.0.0", port=8001)
