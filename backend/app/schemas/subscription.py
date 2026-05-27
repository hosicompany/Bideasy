"""
Subscription tier definitions and feature gating.

Tier hierarchy: free < pro < pro_plus
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# ─── Tier Constants ───
TIER_FREE = "free"
TIER_PRO = "pro"
TIER_PRO_PLUS = "pro_plus"

VALID_TIERS = {TIER_FREE, TIER_PRO, TIER_PRO_PLUS}

# Tier numeric rank for comparison
TIER_RANK = {TIER_FREE: 0, TIER_PRO: 1, TIER_PRO_PLUS: 2}

# ─── Pricing ───
# 월간: 표시 가격 그대로 청구
MONTHLY_PRICES = {
    TIER_FREE: 0,
    TIER_PRO: 14_900,
    TIER_PRO_PLUS: 29_900,
}

# 연간: 1회 결제, 365일 유효. 20% 할인 + 만 단위 라운딩 (실제 21.7%)
ANNUAL_PRICES = {
    TIER_FREE: 0,
    TIER_PRO: 140_000,       # 월환산 11,667원 (vs 월간 14,900원, 21.7% 할인)
    TIER_PRO_PLUS: 280_000,  # 월환산 23,333원 (vs 월간 29,900원, 22.0% 할인)
}

# UI 표시용: 연간 플랜의 월환산 가격 (실제 청구는 ANNUAL_PRICES 사용)
ANNUAL_MONTHLY_PRICES = {
    TIER_FREE: 0,
    TIER_PRO: 11_667,
    TIER_PRO_PLUS: 23_333,
}

# 마케팅용 표기 할인율 (실제는 21.7~22.0%이나 "20% 할인"으로 표기)
ANNUAL_DISCOUNT_DISPLAY_PCT = 20

# ─── Feature Access Map ───
# True = accessible at this tier, False = locked
TIER_FEATURES = {
    TIER_FREE: {
        "feed": True,
        "calculator": True,
        "ai_analysis": True,     # limited to FREE_AI_DAILY_LIMIT/day
        "deep_analysis": False,
        "competition_predict": False,
        "bid_verify": False,
        "agency_profile": False,
        "smart_recommend": False,
        "rate_predict": False,
    },
    TIER_PRO: {
        "feed": True,
        "calculator": True,
        "ai_analysis": True,     # unlimited
        "deep_analysis": True,
        "competition_predict": True,
        "bid_verify": True,
        "agency_profile": False,
        "smart_recommend": False,
        "rate_predict": False,
    },
    TIER_PRO_PLUS: {
        "feed": True,
        "calculator": True,
        "ai_analysis": True,     # unlimited
        "deep_analysis": True,
        "competition_predict": True,
        "bid_verify": True,
        "agency_profile": True,
        "smart_recommend": True,
        "rate_predict": True,
    },
}

# ─── AI Rate Limits ───
FREE_AI_DAILY_LIMIT = 1  # Free tier: 1 AI analysis per day


def has_feature(tier: str, feature: str) -> bool:
    """Check if a tier has access to a feature."""
    return TIER_FEATURES.get(tier, TIER_FEATURES[TIER_FREE]).get(feature, False)


def tier_at_least(user_tier: str, required_tier: str) -> bool:
    """Check if user_tier meets the minimum required tier."""
    return TIER_RANK.get(user_tier, 0) >= TIER_RANK.get(required_tier, 0)


# ─── Display helpers ───
TIER_DISPLAY_NAMES = {
    TIER_FREE: "Free",
    TIER_PRO: "Pro",
    TIER_PRO_PLUS: "Pro+",
}

TIER_DISPLAY_NAMES_KO = {
    TIER_FREE: "무료",
    TIER_PRO: "프로",
    TIER_PRO_PLUS: "프로+",
}


# ─── Pydantic Schemas ───

class SubscriptionInfo(BaseModel):
    tier: str
    tier_display: str
    expires_at: Optional[datetime] = None
    is_active: bool
    billing_cycle: Optional[str] = None  # monthly | annual

    class Config:
        from_attributes = True


class SubscribeRequest(BaseModel):
    tier: str  # "pro" or "pro_plus"
    billing_cycle: str = "monthly"  # "monthly" or "annual"


class SubscribeOrderResponse(BaseModel):
    order_id: str
    amount: int
    order_name: str
    customer_name: str
    toss_client_key: str
    tier: str
    billing_cycle: str
