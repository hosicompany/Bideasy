from pydantic import BaseModel
from typing import List, Optional


class AgencyProfile(BaseModel):
    """기관 프로파일링 결과"""
    organization: str
    total_bids: int                     # 분석 기간 내 총 입찰 건수
    avg_winning_rate: Optional[float]   # 평균 낙찰률 (%)
    min_winning_rate: Optional[float]   # 최저 낙찰률
    max_winning_rate: Optional[float]   # 최고 낙찰률
    avg_participants: Optional[float]   # 평균 참여 업체 수
    avg_winning_price: Optional[float]  # 평균 낙찰 금액
    winning_rate_distribution: dict     # 낙찰률 구간별 분포
    recommendation: str                 # 투찰 전략 추천


class AgencyProfileRequest(BaseModel):
    organization: str       # 기관명 (예: "강남구청")
    months: int = 6         # 분석 기간 (기본 6개월)
