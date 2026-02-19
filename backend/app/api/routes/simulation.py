"""
투찰 시뮬레이션 API 라우터
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date

from app.services.simulation_service import (
    get_simulation_service, 
    AgencyType
)

router = APIRouter(prefix="/simulation", tags=["simulation"])


class SimulationRequest(BaseModel):
    """시뮬레이션 요청 모델"""
    base_amount: float = Field(
        ..., 
        description="기초금액 (원)",
        example=100000000,
        gt=0
    )
    a_value: float = Field(
        default=0,
        description="A값 - 시설공사용 (원)",
        example=15000000,
        ge=0
    )
    bid_type: str = Field(
        default="construction",
        description="입찰 유형 (construction, goods, service)",
        example="construction"
    )
    estimated_amount: Optional[float] = Field(
        default=None,
        description="추정가격 (원) - 낙찰하한율 결정용",
        example=100000000
    )
    bid_date: Optional[str] = Field(
        default=None,
        description="입찰일 (YYYY-MM-DD) - 2026.1.30 기준 분기",
        example="2026-02-15"
    )
    agency_type: str = Field(
        default="national",
        description="발주기관 유형 (national, local, public_corp)",
        example="national"
    )


class MonteCarloRequest(BaseModel):
    """몬테카를로 시뮬레이션 요청"""
    base_amount: float = Field(..., description="기초금액", gt=0)
    agency_type: str = Field(default="national")
    num_simulations: int = Field(default=10000, ge=1000, le=100000)


@router.post("/optimal-bid")
async def calculate_optimal_bid(request: SimulationRequest):
    """
    최적 투찰가 계산
    
    몬테카를로 시뮬레이션 + 규칙 기반으로 최적 투찰가를 추천합니다.
    """
    try:
        service = get_simulation_service()
        
        # 날짜 파싱
        bid_date = None
        if request.bid_date:
            try:
                bid_date = date.fromisoformat(request.bid_date)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요."
                )
        
        # 발주기관 유형 매핑
        agency_map = {
            "national": AgencyType.NATIONAL,
            "local": AgencyType.LOCAL,
            "public_corp": AgencyType.PUBLIC_CORP
        }
        agency_type = agency_map.get(request.agency_type, AgencyType.NATIONAL)
        
        result = service.calculate_optimal_bid(
            base_amount=request.base_amount,
            a_value=request.a_value,
            bid_type=request.bid_type,
            estimated_amount=request.estimated_amount,
            bid_date=bid_date,
            agency_type=agency_type
        )
        
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"시뮬레이션 오류: {str(e)}")


@router.post("/monte-carlo")
async def run_monte_carlo(request: MonteCarloRequest):
    """
    몬테카를로 시뮬레이션 실행
    
    예정가격 분포를 시뮬레이션합니다.
    """
    try:
        service = get_simulation_service()
        
        agency_map = {
            "national": AgencyType.NATIONAL,
            "local": AgencyType.LOCAL,
            "public_corp": AgencyType.PUBLIC_CORP
        }
        agency_type = agency_map.get(request.agency_type, AgencyType.NATIONAL)
        
        result = service.run_monte_carlo(
            base_amount=request.base_amount,
            agency_type=agency_type,
            num_simulations=request.num_simulations
        )
        
        return {
            "base_amount": request.base_amount,
            "price_distribution": result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lower-limits")
async def get_lower_limits(
    bid_type: str = "construction",
    estimated_amount: float = 100000000,
    bid_date: Optional[str] = None
):
    """
    낙찰하한율 조회
    
    입찰 유형과 추정가격에 따른 낙찰하한율을 반환합니다.
    """
    try:
        service = get_simulation_service()
        
        date_obj = None
        if bid_date:
            date_obj = date.fromisoformat(bid_date)
        
        lower_limit = service.get_lower_limit(
            bid_type=bid_type,
            estimated_amount=estimated_amount,
            bid_date=date_obj
        )
        
        return {
            "bid_type": bid_type,
            "estimated_amount": estimated_amount,
            "lower_limit": lower_limit,
            "lower_limit_pct": f"{lower_limit * 100:.3f}%",
            "regulation_version": "2026" if date_obj and date_obj >= date(2026, 1, 30) else "legacy"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
