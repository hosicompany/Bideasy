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
MONTHLY_PRICES = {
    TIER_FREE: 0,
    TIER_PRO: 14_900,
    TIER_PRO_PLUS: 29_900,
}

ANNUAL_MONTHLY_PRICES = {
    TIER_FREE: 0,
    TIER_PRO: 12_400,      # 2 months free
    TIER_PRO_PLUS: 24_900,  # 2 months free
}

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
