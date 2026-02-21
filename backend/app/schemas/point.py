from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# 과금 상수
BID_COPY_COST = 500  # 투찰금액 복사 1건당 500원
SIGNUP_BONUS = 3000  # 신규 가입 보너스 3,000원
DAILY_FREE_COPIES = 1  # 일일 무료 복사 횟수


class PointBalance(BaseModel):
    points: int
    formatted: str  # "3,000원"


class PointDeductRequest(BaseModel):
    bid_no: str  # 어떤 공고의 투찰금액을 복사하는지


class PointChargeRequest(BaseModel):
    amount: int  # 충전 금액


class PointTransaction(BaseModel):
    id: int
    amount: int
    balance_after: int
    tx_type: str
    description: Optional[str] = None
    bid_no: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PointDeductResponse(BaseModel):
    success: bool
    remaining_points: int
    cost: int
    message: str
    was_free: bool = False


class PointChargeResponse(BaseModel):
    success: bool
    charged_amount: int
    remaining_points: int
    message: str


class DailyFreeStatus(BaseModel):
    available: bool
    used_today: int
    max_daily: int = DAILY_FREE_COPIES
