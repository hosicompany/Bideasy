"""
Subscription tier definitions and feature gating.

Tier hierarchy: free < pro < pro_plus

신규 가입 14일 Pro 체험:
- 가입 시 trial_started_at = now, trial_expires_at = now + 14일 자동 설정
- 체험 활성 동안 effective tier = "pro" (실제 user.tier 는 "free" 유지)
- 만료 후 자동 Free 다운그레이드 (별도 작업 불필요 — get_effective_tier 가 자동 판단)
- 재체험 불가 (trial_started_at 이 None 이 아니면 새 체험 시작 거부)
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta, timezone

# ─── Tier Constants ───
TIER_FREE = "free"
TIER_PRO = "pro"
TIER_PRO_PLUS = "pro_plus"

VALID_TIERS = {TIER_FREE, TIER_PRO, TIER_PRO_PLUS}

# Tier numeric rank for comparison
TIER_RANK = {TIER_FREE: 0, TIER_PRO: 1, TIER_PRO_PLUS: 2}

# ─── Pricing ───
# 월간: 표시 가격 그대로 청구
# 2026-07 런칭 기념가 개편: Pro 24,900→19,900 (2만원 벽 돌파), Pro+ 49,900→39,900 (1:2 사다리)
MONTHLY_PRICES = {
    TIER_FREE: 0,
    TIER_PRO: 19_900,
    TIER_PRO_PLUS: 39_900,
}

# 연간: 1회 결제, 365일 유효. 약 20% 할인 + 천 단위 라운딩
ANNUAL_PRICES = {
    TIER_FREE: 0,
    TIER_PRO: 191_000,       # 월환산 15,917원 (vs 월간 19,900원, 약 20% 할인)
    TIER_PRO_PLUS: 383_000,  # 월환산 31,917원 (vs 월간 39,900원, 약 20% 할인)
}

# UI 표시용: 연간 플랜의 월환산 가격 (실제 청구는 ANNUAL_PRICES 사용)
ANNUAL_MONTHLY_PRICES = {
    TIER_FREE: 0,
    TIER_PRO: 15_917,
    TIER_PRO_PLUS: 31_917,
}

# 마케팅용 표기 할인율 (실제 약 20%)
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


# ─── Trial Configuration ───
TRIAL_DAYS = 14                 # 신규 가입 시 자동 부여 체험 기간
TRIAL_TIER = TIER_PRO           # 체험 중 적용 tier (Pro 기능 전체 개방)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLAlchemy 가 naive datetime 을 반환할 수 있으니 UTC aware 로 통일."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_trial_active(user) -> bool:
    """현재 시점에 체험이 활성 상태인지."""
    trial_exp = _aware(getattr(user, "trial_expires_at", None))
    if trial_exp is None:
        return False
    return trial_exp > datetime.now(timezone.utc)


def has_used_trial(user) -> bool:
    """이미 체험을 시작한 적이 있는지 (active 여부 무관, 재체험 방지용)."""
    return getattr(user, "trial_started_at", None) is not None


def trial_days_remaining(user) -> int:
    """체험 잔여 일수. 만료/없음이면 0."""
    trial_exp = _aware(getattr(user, "trial_expires_at", None))
    if trial_exp is None:
        return 0
    delta = trial_exp - datetime.now(timezone.utc)
    return max(0, delta.days + (1 if delta.seconds > 0 else 0))


def get_effective_tier(user) -> str:
    """
    사용자의 현재 유효 tier 를 반환.

    우선순위:
      1) 유효한 유료 구독 (subscription_expires_at > now)  → user.tier
      2) 활성 체험 (trial_expires_at > now)                 → TRIAL_TIER (= Pro)
      3) 그 외                                              → "free"
    """
    now = datetime.now(timezone.utc)
    user_tier = getattr(user, "tier", "free") or "free"

    # 1) 유료 구독 — expires_at = None 은 무기한(admin 부여·레거시) 으로 활성 취급
    if user_tier != "free":
        expires_at = _aware(getattr(user, "subscription_expires_at", None))
        if expires_at is None or expires_at > now:
            return user_tier

    # 2) 체험
    if is_trial_active(user):
        return TRIAL_TIER

    # 3) Free
    return "free"


# ─── Win-back 첫 달 50% 할인 ───────────────────────────────
# Trial 사용자(활성 또는 만료 7일 이내)가 *첫* 결제 시 자동 적용.
# Toss 결제 시점에 amount 가 이미 할인된 금액으로 결정 → 사용자가 별도 쿠폰
# 코드 입력 안 함.
WINBACK_DISCOUNT_PCT = 50
WINBACK_REASON_CODE = "TRIAL_WINBACK_50"
WINBACK_GRACE_DAYS = 7  # Trial 만료 후 N일 동안 자격 유지


def is_winback_eligible(user, db) -> bool:
    """
    사용자가 첫 달 50% 자동 할인 대상인지.

    조건 (모두 충족):
      1) Trial 시작한 적 있음 (trial_started_at != None)
      2) 첫 결제 (CONFIRMED PaymentOrder 없음)
      3) Trial 이 '만료'됨 + 만료 후 WINBACK_GRACE_DAYS 일 이내 (이탈자 전용)
         — 체험 활성 중엔 정가. 14일 체험이 곧 전환 인센티브라 중복 할인 안 함.
         할인은 "체험 써보고도 결제 안 하고 떠난 고객"을 되찾는 회수 레버로만.

    DB 조회를 1회만 하도록 호출자에서 db 세션 전달.
    """
    from app.db import models  # 순환 import 방지

    # 1) Trial 시작 안 함 → 자격 없음
    trial_exp = _aware(getattr(user, "trial_expires_at", None))
    if not getattr(user, "trial_started_at", None) or trial_exp is None:
        return False

    # 3) 이탈자 전용 — Trial 이 '만료'된 뒤 grace(7일) 이내만.
    now = datetime.now(timezone.utc)
    if now <= trial_exp:  # 아직 체험 중 → 정가 (체험 자체가 전환 인센티브)
        return False
    if now > trial_exp + timedelta(days=WINBACK_GRACE_DAYS):  # grace 초과
        return False

    # 2) 이미 결제 이력 있음 → 자격 없음
    has_payment = (
        db.query(models.PaymentOrder.id)
        .filter(
            models.PaymentOrder.user_id == user.id,
            models.PaymentOrder.status == "CONFIRMED",
        )
        .first()
    )
    if has_payment:
        return False

    return True


def winback_expires_at(user) -> Optional[datetime]:
    """자격이 만료되는 시각 (Trial 만료 + grace days)."""
    trial_exp = _aware(getattr(user, "trial_expires_at", None))
    if trial_exp is None:
        return None
    return trial_exp + timedelta(days=WINBACK_GRACE_DAYS)


def calculate_winback_discount(amount: int) -> int:
    """주어진 정가의 50% 할인액. 1원 단위 절사."""
    return (amount * WINBACK_DISCOUNT_PCT) // 100


def activate_trial(user) -> None:
    """
    사용자에게 14일 Pro 체험을 활성화한다.

    이미 체험을 사용한 이력이 있으면 (trial_started_at != None) 아무것도 안 함.
    호출 측에서 db.commit() 책임. 캘러는 신규 가입 흐름에서만 호출.
    """
    if has_used_trial(user):
        return  # 재체험 방지
    now = datetime.now(timezone.utc)
    user.trial_started_at = now
    user.trial_expires_at = now + timedelta(days=TRIAL_DAYS)


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

    # Trial 정보 (frontend 가 잔여일 표시·결제 유도용)
    is_trial: bool = False
    trial_expires_at: Optional[datetime] = None
    trial_days_remaining: int = 0
    has_used_trial: bool = False

    # 첫 달 50% 할인 자격 (Trial 사용자가 첫 결제 시)
    winback_eligible: bool = False
    winback_expires_at: Optional[datetime] = None
    winback_discount_pct: int = 0  # 0 = 자격 없음, 50 = WINBACK_DISCOUNT_PCT

    class Config:
        from_attributes = True


class TrialStatus(BaseModel):
    """경량 체험 상태 조회용 (마이페이지·익스텐션 헤더 등)."""
    is_active: bool
    days_remaining: int
    expires_at: Optional[datetime] = None
    has_used: bool


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
