"""
관리자 대시보드용 Pydantic 응답 스키마
=====================================
admin 라우터들의 응답을 일관되게 직렬화하기 위한 모음.
"""
from typing import Any, Optional
from pydantic import BaseModel


# ─── 페이지네이션 공통 ─────────────────────────────────────

class PaginatedResponse(BaseModel):
    """페이지네이션 응답 공통 구조 (관리자 list API 공용)."""
    items: list[Any]
    total: int
    page: int
    size: int
    total_pages: int


# ─── 대시보드: /stats/revenue ──────────────────────────────

class RevenueWindow(BaseModel):
    revenue: int
    orders: int


class RevenueByCycle(BaseModel):
    pro_monthly: int = 0
    pro_annual: int = 0
    pro_plus_monthly: int = 0
    pro_plus_annual: int = 0


class RevenueSeriesPoint(BaseModel):
    date: str  # YYYY-MM-DD
    amount: int
    count: int


class RevenueStats(BaseModel):
    today: RevenueWindow
    this_week: RevenueWindow
    this_month: RevenueWindow
    mrr: int  # 활성 월간 구독 × 월 가격 합
    series: list[RevenueSeriesPoint]
    by_tier: RevenueByCycle


# ─── 대시보드: /stats/users ────────────────────────────────

class UserTierBreakdown(BaseModel):
    free: int = 0
    pro: int = 0
    pro_plus: int = 0


class UserStatusBreakdown(BaseModel):
    trial_active: int = 0
    trial_expired_only: int = 0  # 체험 만료 + 유료 구독 없음
    paid_active: int = 0
    free_only: int = 0  # 체험 시작 안 함


class TrialConversion(BaseModel):
    trial_started_count: int
    converted_to_paid: int
    rate: float  # 0.0~1.0


class SignupSeriesPoint(BaseModel):
    date: str
    count: int


class UserStats(BaseModel):
    total: int
    by_tier: UserTierBreakdown
    by_status: UserStatusBreakdown
    signups_series: list[SignupSeriesPoint]
    trial_conversion: TrialConversion


# ─── 대시보드: /stats/ai-cost ──────────────────────────────

class AICostWindow(BaseModel):
    calls: int
    tokens: int
    estimated_usd: float


class AICostSeriesPoint(BaseModel):
    date: str
    calls: int
    tokens: int
    estimated_usd: float


class AICostStats(BaseModel):
    today: AICostWindow
    this_month: AICostWindow
    series: list[AICostSeriesPoint]
    by_model: dict[str, dict[str, int]]  # { "gpt-4o-mini": {"calls", "tokens"} }


# ─── 대시보드: /stats/system-health ───────────────────────

class ComponentHealth(BaseModel):
    ok: bool
    detail: Optional[str] = None


class CeleryHealth(BaseModel):
    ok: bool
    workers: int = 0
    queues: dict[str, int] = {}
    detail: Optional[str] = None


class SystemHealth(BaseModel):
    db: ComponentHealth
    redis: ComponentHealth
    celery: CeleryHealth
    last_crawl_at: Optional[str] = None
    last_calibration_at: Optional[str] = None
    pending_payments_24h: int = 0


# ─── 대시보드: /stats/autocalibrate-status ────────────────

class AutocalibrateMetrics(BaseModel):
    total: Optional[int] = None
    win_rate: Optional[float] = None
    pass_rate: Optional[float] = None
    dropout_rate: Optional[float] = None
    rate_error: Optional[float] = None
    risk_calibration_error: Optional[float] = None


class AutocalibrateActive(BaseModel):
    version_id: str
    created_at: str
    parent_version: Optional[str] = None
    metrics: Optional[AutocalibrateMetrics] = None


class AutocalibrateHistoryEvent(BaseModel):
    at: str
    event: str  # BOOTSTRAP | ADOPTED | REJECTED
    version_id: Optional[str] = None
    detail: dict[str, Any] = {}


class AutocalibrateStatus(BaseModel):
    active: Optional[AutocalibrateActive]
    recent_history: list[AutocalibrateHistoryEvent]
    next_scheduled: Optional[str] = None  # 다음 월요일 04:00 KST ISO
