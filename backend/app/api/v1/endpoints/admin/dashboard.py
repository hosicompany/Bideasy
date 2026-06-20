"""
관리자 대시보드 통계 API
=========================
사업 운영 지표를 집계해서 admin 대시보드에 표시.

Endpoints:
- GET /admin/stats/revenue          — 일/주/월 매출, MRR, 시리즈, tier별
- GET /admin/stats/users            — 가입 추이, tier 분포, Trial 전환율
- GET /admin/stats/ai-cost          — AI 분석 호출·토큰·비용
- GET /admin/stats/system-health    — DB·Redis·Celery·크롤·결제 헬스
- GET /admin/stats/autocalibrate-status — active 버전·이력·다음 실행
"""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.db import models
from app.db.session import get_db
from app.schemas import admin as admin_schemas
from app.schemas.subscription import (
    MONTHLY_PRICES,
    TIER_FREE,
    TIER_PRO,
    TIER_PRO_PLUS,
)

router = APIRouter()

# GPT-4o-mini 추정 단가 (2026-05 기준): $0.15 / 1M input + $0.60 / 1M output
# 단순화: input + output 합쳐 평균 $0.40 / 1M token 가정
_GPT4O_MINI_USD_PER_TOKEN = 0.40 / 1_000_000

_STRATEGY_DIR = Path(__file__).resolve().parents[5] / "data" / "strategy"
_PREDICTIONS_LOG = Path(__file__).resolve().parents[5] / "data" / "predictions_log.jsonl"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """naive 면 UTC 로 간주."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@router.get("/stats/attribution")
def attribution_stats(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """유입 채널별 가입·전환 — signup_source(first-touch) 기준 집계.

    trial 은 user.tier 를 바꾸지 않으므로(get_effective_tier 가 오버레이) tier != free
    = 실제 유료 전환. 외부 분석도구·쿠키 없이 우리 DB 만으로 채널→가입→매출 귀속.
    """
    rows = (
        db.query(
            models.User.signup_source.label("source"),
            func.count(models.User.id).label("signups"),
            func.coalesce(
                func.sum(case((models.User.tier != TIER_FREE, 1), else_=0)), 0
            ).label("paid"),
        )
        .group_by(models.User.signup_source)
        .order_by(func.count(models.User.id).desc())
        .all()
    )
    channels = []
    for r in rows:
        signups = int(r.signups or 0)
        paid = int(r.paid or 0)
        channels.append(
            {
                "source": r.source or "(unknown)",
                "signups": signups,
                "paid": paid,
                "conversion_pct": round(paid / signups * 100, 1) if signups else 0.0,
            }
        )
    return {
        "channels": channels,
        "total_signups": sum(c["signups"] for c in channels),
        "total_paid": sum(c["paid"] for c in channels),
    }


# ─── /stats/revenue ───────────────────────────────────────

@router.get("/stats/revenue", response_model=admin_schemas.RevenueStats)
def get_revenue_stats(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    now = _utcnow()
    today_start = _start_of_day(now)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    def _window_sum(start: datetime) -> admin_schemas.RevenueWindow:
        r, c = db.query(
            func.coalesce(func.sum(models.PaymentOrder.amount), 0),
            func.count(models.PaymentOrder.id),
        ).filter(
            models.PaymentOrder.status == "CONFIRMED",
            models.PaymentOrder.confirmed_at >= start,
            # 환불된 금액 차감 (전액 환불은 제외, 부분 환불은 그대로 카운트)
            models.PaymentOrder.refunded_at.is_(None),
        ).one()
        return admin_schemas.RevenueWindow(revenue=int(r or 0), orders=int(c or 0))

    today = _window_sum(today_start)
    this_week = _window_sum(week_start)
    this_month = _window_sum(month_start)

    # MRR: 활성 월간 구독자 × Pro/Pro+ 가격
    # 단순화: 활성 tier 사용자 × 월 가격 (연간 구독은 12분의 1 분배 안 함)
    active_pro = db.query(func.count(models.User.id)).filter(
        models.User.tier == TIER_PRO,
        # 활성: subscription_expires_at 미래 또는 None (무기한)
    ).scalar() or 0
    active_pro_plus = db.query(func.count(models.User.id)).filter(
        models.User.tier == TIER_PRO_PLUS,
    ).scalar() or 0
    mrr = (
        active_pro * MONTHLY_PRICES[TIER_PRO]
        + active_pro_plus * MONTHLY_PRICES[TIER_PRO_PLUS]
    )

    # 일별 시리즈 (최근 N일)
    series_start = today_start - timedelta(days=days - 1)
    rows = db.query(
        func.date(models.PaymentOrder.confirmed_at).label("d"),
        func.coalesce(func.sum(models.PaymentOrder.amount), 0).label("amt"),
        func.count(models.PaymentOrder.id).label("cnt"),
    ).filter(
        models.PaymentOrder.status == "CONFIRMED",
        models.PaymentOrder.confirmed_at >= series_start,
        models.PaymentOrder.refunded_at.is_(None),
    ).group_by(func.date(models.PaymentOrder.confirmed_at)).all()
    rows_by_date = {str(r.d): r for r in rows}

    series = []
    for i in range(days):
        d = (series_start + timedelta(days=i)).date()
        ds = d.isoformat()
        r = rows_by_date.get(ds)
        series.append(
            admin_schemas.RevenueSeriesPoint(
                date=ds,
                amount=int(r.amt) if r else 0,
                count=int(r.cnt) if r else 0,
            )
        )

    # 구독 vs 포인트 vs 환불 분리: order_id prefix 로 추정
    # SUB_ → subscription, 그 외 → points
    # 추가 분리는 Phase C 에서 (지금은 합산)
    by_tier = admin_schemas.RevenueByCycle()

    return admin_schemas.RevenueStats(
        today=today,
        this_week=this_week,
        this_month=this_month,
        mrr=mrr,
        series=series,
        by_tier=by_tier,
    )


# ─── /stats/users ─────────────────────────────────────────

@router.get("/stats/users", response_model=admin_schemas.UserStats)
def get_user_stats(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    now = _utcnow()
    today_start = _start_of_day(now)

    total = db.query(func.count(models.User.id)).scalar() or 0

    # tier 분포
    tier_rows = db.query(
        models.User.tier, func.count(models.User.id)
    ).group_by(models.User.tier).all()
    tier_map = dict(tier_rows)
    by_tier = admin_schemas.UserTierBreakdown(
        free=tier_map.get(TIER_FREE, 0),
        pro=tier_map.get(TIER_PRO, 0),
        pro_plus=tier_map.get(TIER_PRO_PLUS, 0),
    )

    # status 분포 (Trial 활성/만료, 유료 활성, free only)
    all_users = db.query(
        models.User.tier,
        models.User.subscription_expires_at,
        models.User.trial_started_at,
        models.User.trial_expires_at,
    ).all()
    status = admin_schemas.UserStatusBreakdown()
    for u in all_users:
        trial_exp = _aware(u.trial_expires_at)
        sub_exp = _aware(u.subscription_expires_at)
        is_trial_active = trial_exp is not None and trial_exp > now
        is_paid_active = u.tier and u.tier != TIER_FREE and (
            sub_exp is None or sub_exp > now
        )
        if is_paid_active:
            status.paid_active += 1
        elif is_trial_active:
            status.trial_active += 1
        elif u.trial_started_at is not None:
            status.trial_expired_only += 1
        else:
            status.free_only += 1

    # 신규 가입 시리즈 (trial_started_at fallback — User.created_at 없음)
    series_start = today_start - timedelta(days=days - 1)
    rows = db.query(
        func.date(models.User.trial_started_at).label("d"),
        func.count(models.User.id).label("cnt"),
    ).filter(
        models.User.trial_started_at >= series_start,
    ).group_by(func.date(models.User.trial_started_at)).all()
    by_date = {str(r.d): r.cnt for r in rows}
    signups_series = [
        admin_schemas.SignupSeriesPoint(
            date=(series_start + timedelta(days=i)).date().isoformat(),
            count=int(by_date.get((series_start + timedelta(days=i)).date().isoformat(), 0)),
        )
        for i in range(days)
    ]

    # Trial 전환율: trial_started_at 있는 사용자 중 paid_active 비율
    trial_started_count = db.query(func.count(models.User.id)).filter(
        models.User.trial_started_at.isnot(None),
    ).scalar() or 0
    # 유료 전환: tier=pro/pro_plus 이고 trial_started_at 있는 사용자
    converted_to_paid = db.query(func.count(models.User.id)).filter(
        models.User.trial_started_at.isnot(None),
        models.User.tier.in_([TIER_PRO, TIER_PRO_PLUS]),
    ).scalar() or 0
    rate = (converted_to_paid / trial_started_count) if trial_started_count else 0.0

    return admin_schemas.UserStats(
        total=total,
        by_tier=by_tier,
        by_status=status,
        signups_series=signups_series,
        trial_conversion=admin_schemas.TrialConversion(
            trial_started_count=trial_started_count,
            converted_to_paid=converted_to_paid,
            rate=round(rate, 4),
        ),
    )


# ─── /stats/ai-cost ───────────────────────────────────────

@router.get("/stats/ai-cost", response_model=admin_schemas.AICostStats)
def get_ai_cost_stats(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    now = _utcnow()
    today_start = _start_of_day(now)
    month_start = today_start.replace(day=1)

    def _window(start: datetime) -> admin_schemas.AICostWindow:
        calls, tokens = db.query(
            func.count(models.AIAnalysisLog.bid_no),
            func.coalesce(func.sum(models.AIAnalysisLog.token_usage), 0),
        ).filter(
            models.AIAnalysisLog.created_at >= start,
        ).one()
        return admin_schemas.AICostWindow(
            calls=int(calls or 0),
            tokens=int(tokens or 0),
            estimated_usd=round((tokens or 0) * _GPT4O_MINI_USD_PER_TOKEN, 4),
        )

    today = _window(today_start)
    this_month = _window(month_start)

    # 일별 시리즈
    series_start = today_start - timedelta(days=days - 1)
    rows = db.query(
        func.date(models.AIAnalysisLog.created_at).label("d"),
        func.count(models.AIAnalysisLog.bid_no).label("cnt"),
        func.coalesce(func.sum(models.AIAnalysisLog.token_usage), 0).label("tok"),
    ).filter(
        models.AIAnalysisLog.created_at >= series_start,
    ).group_by(func.date(models.AIAnalysisLog.created_at)).all()
    by_date = {str(r.d): r for r in rows}
    series = []
    for i in range(days):
        d = (series_start + timedelta(days=i)).date().isoformat()
        r = by_date.get(d)
        toks = int(r.tok) if r else 0
        series.append(admin_schemas.AICostSeriesPoint(
            date=d,
            calls=int(r.cnt) if r else 0,
            tokens=toks,
            estimated_usd=round(toks * _GPT4O_MINI_USD_PER_TOKEN, 4),
        ))

    # 모델별 집계
    model_rows = db.query(
        models.AIAnalysisLog.llm_model,
        func.count(models.AIAnalysisLog.bid_no),
        func.coalesce(func.sum(models.AIAnalysisLog.token_usage), 0),
    ).group_by(models.AIAnalysisLog.llm_model).all()
    by_model = {
        (m or "unknown"): {"calls": int(c), "tokens": int(t)}
        for m, c, t in model_rows
    }

    return admin_schemas.AICostStats(
        today=today,
        this_month=this_month,
        series=series,
        by_model=by_model,
    )


# ─── /stats/system-health ─────────────────────────────────

@router.get("/stats/system-health", response_model=admin_schemas.SystemHealth)
def get_system_health(
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    # DB
    try:
        t0 = time.time()
        db.execute(func.now() if hasattr(func, 'now') else None) if False else db.query(func.count(models.User.id)).scalar()
        db_health = admin_schemas.ComponentHealth(
            ok=True, detail=f"{(time.time() - t0) * 1000:.1f}ms"
        )
    except Exception as e:
        db_health = admin_schemas.ComponentHealth(ok=False, detail=str(e))

    # Redis
    try:
        from app.core.config import settings
        import redis
        r = redis.from_url(getattr(settings, "celery_broker", None) or "redis://redis:6379/0")
        r.ping()
        redis_health = admin_schemas.ComponentHealth(ok=True)
    except Exception as e:
        redis_health = admin_schemas.ComponentHealth(ok=False, detail=str(e))

    # Celery
    try:
        from app.core.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=2.0)
        active = inspect.active() or {}
        queues = {k: len(v) for k, v in active.items()}
        celery_health = admin_schemas.CeleryHealth(
            ok=bool(active), workers=len(active), queues=queues,
        )
    except Exception as e:
        celery_health = admin_schemas.CeleryHealth(ok=False, detail=str(e))

    # 마지막 크롤
    last_crawl = db.query(func.max(models.OpeningResult.crawled_at)).scalar()
    last_crawl_iso = last_crawl.isoformat() if last_crawl else None

    # 마지막 자가보정 (history.jsonl 의 ADOPTED 이벤트)
    last_calibration_iso = None
    history_path = _STRATEGY_DIR / "history.jsonl"
    if history_path.exists():
        try:
            lines = history_path.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines):
                ev = json.loads(line)
                if ev.get("event") == "ADOPTED":
                    last_calibration_iso = ev.get("at")
                    break
        except Exception:
            pass

    # 24시간+ PENDING 결제
    cutoff = _utcnow() - timedelta(hours=24)
    pending_old = db.query(func.count(models.PaymentOrder.id)).filter(
        models.PaymentOrder.status == "PENDING",
        models.PaymentOrder.created_at < cutoff,
    ).scalar() or 0

    return admin_schemas.SystemHealth(
        db=db_health,
        redis=redis_health,
        celery=celery_health,
        last_crawl_at=last_crawl_iso,
        last_calibration_at=last_calibration_iso,
        pending_payments_24h=int(pending_old),
    )


# ─── /stats/autocalibrate-status ──────────────────────────

def _next_monday_4am_kst() -> str:
    """다음 월요일 04:00 KST (자동 자가보정 스케줄) ISO 8601."""
    now = _utcnow()
    # KST = UTC+9
    kst_now = now + timedelta(hours=9)
    days_ahead = (7 - kst_now.weekday()) % 7  # 월요일 = 0
    if days_ahead == 0 and kst_now.hour >= 4:
        days_ahead = 7
    next_kst = (kst_now + timedelta(days=days_ahead)).replace(
        hour=4, minute=0, second=0, microsecond=0
    )
    next_utc = next_kst - timedelta(hours=9)
    return next_utc.replace(tzinfo=timezone.utc).isoformat()


@router.get("/stats/autocalibrate-status", response_model=admin_schemas.AutocalibrateStatus)
def get_autocalibrate_status(
    _admin=Depends(require_admin),
):
    active_path = _STRATEGY_DIR / "active.json"
    history_path = _STRATEGY_DIR / "history.jsonl"

    active = None
    if active_path.exists():
        try:
            data = json.loads(active_path.read_text(encoding="utf-8"))
            metrics_data = data.get("metrics") or {}
            active = admin_schemas.AutocalibrateActive(
                version_id=data.get("version_id", "unknown"),
                created_at=data.get("created_at", ""),
                parent_version=data.get("parent_version"),
                metrics=admin_schemas.AutocalibrateMetrics(**metrics_data) if metrics_data else None,
            )
        except Exception:
            pass

    history = []
    if history_path.exists():
        try:
            lines = history_path.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines[-20:]):  # 최근 20건
                ev = json.loads(line)
                history.append(admin_schemas.AutocalibrateHistoryEvent(
                    at=ev.get("at", ""),
                    event=ev.get("event", ""),
                    version_id=ev.get("version_id"),
                    detail=ev.get("detail", {}),
                ))
        except Exception:
            pass

    return admin_schemas.AutocalibrateStatus(
        active=active,
        recent_history=history,
        next_scheduled=_next_monday_4am_kst(),
    )

# ─── GET /admin/daily-report ──────────────────────────────────

@router.get("/daily-report")
def get_daily_report(
    date: str | None = Query(None, description="YYYY-MM-DD 기본=어제"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """일일 운영 리포트 — 매일 09:00 Celery 가 보내는 것과 동일 데이터.

    /admin#/dashboard 상단의 "어제의 운영 리포트" 카드에서 호출.
    """
    from datetime import date as date_cls
    from app.services.admin_daily_report import collect_daily_report

    target = None
    if date:
        try:
            target = date_cls.fromisoformat(date)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(400, "date 형식은 YYYY-MM-DD")

    return collect_daily_report(db, target=target)

