"""
일일 운영 리포트 데이터 수집

CEO 가 매일 09:00 KST 자동 발송받는 운영 지표 일괄 집계.

호출처:
- app/tasks/admin_report_tasks.py (Celery beat 매일 09:00)
- app/api/v1/endpoints/admin/dashboard.py (GET /admin/daily-report)

공통 함수: collect_daily_report(db, date) → dict
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models


def _day_bounds(target: date_cls) -> tuple[datetime, datetime]:
    """target 일 0시~다음 날 0시 (naive UTC, DB 저장값과 동일 형식)."""
    start = datetime.combine(target, datetime.min.time())
    end = start + timedelta(days=1)
    return start, end


def _yesterday_kst() -> date_cls:
    """KST 기준 어제 날짜 (운영 보고서는 어제 데이터 기준)."""
    # KST = UTC + 9. 단순화: UTC 자정 기준 어제 계산
    return (datetime.now(timezone.utc) - timedelta(days=1)).date()


def collect_daily_report(
    db: Session,
    target: date_cls | None = None,
) -> dict[str, Any]:
    """
    어제(또는 지정일)의 운영 지표를 수집한다.

    반환 dict:
      target_date, revenue, users, conversion, ai_usage, autocalibrate,
      system_health, anomalies, summary_line (단일 문자열, 메시지 발송용)
    """
    if target is None:
        target = _yesterday_kst()

    start, end = _day_bounds(target)

    # ─── 1. 매출 ────────────────────────────────────────────
    confirmed_yday = (
        db.query(
            func.count(models.PaymentOrder.id),
            func.coalesce(func.sum(models.PaymentOrder.amount), 0),
        )
        .filter(
            models.PaymentOrder.status == "CONFIRMED",
            models.PaymentOrder.confirmed_at >= start,
            models.PaymentOrder.confirmed_at < end,
        )
        .one()
    )
    yday_count, yday_amount = confirmed_yday

    # 누적 (이번 달)
    month_start = datetime(target.year, target.month, 1)
    month_total = (
        db.query(func.coalesce(func.sum(models.PaymentOrder.amount), 0))
        .filter(
            models.PaymentOrder.status == "CONFIRMED",
            models.PaymentOrder.confirmed_at >= month_start,
            models.PaymentOrder.confirmed_at < end,
        )
        .scalar()
    )

    # MRR 추정 (활성 구독자 × 가격)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    active_pro = (
        db.query(func.count(models.User.id))
        .filter(
            models.User.tier == "pro",
            models.User.subscription_expires_at > now,
        )
        .scalar() or 0
    )
    active_pro_plus = (
        db.query(func.count(models.User.id))
        .filter(
            models.User.tier == "pro_plus",
            models.User.subscription_expires_at > now,
        )
        .scalar() or 0
    )
    mrr_estimate = active_pro * 24900 + active_pro_plus * 49900

    # ─── 2. 사용자 ──────────────────────────────────────────
    # 신규 가입 (trial_started_at = 가입 시점 자동)
    new_signups = (
        db.query(func.count(models.User.id))
        .filter(
            models.User.trial_started_at >= start,
            models.User.trial_started_at < end,
        )
        .scalar() or 0
    )

    total_users = db.query(func.count(models.User.id)).scalar() or 0

    # Trial 활성 / 만료
    trial_active = (
        db.query(func.count(models.User.id))
        .filter(
            models.User.trial_expires_at > now,
            models.User.tier == "free",
        )
        .scalar() or 0
    )

    # ─── 3. Trial → 결제 전환율 (어제 만료된 사용자 중 결제 한 비율) ─
    # 어제 만료 사용자
    yday_trial_expired_qs = db.query(models.User).filter(
        models.User.trial_expires_at >= start,
        models.User.trial_expires_at < end,
    )
    yday_trial_expired = yday_trial_expired_qs.count()

    # 그 중 어제 또는 그 이전에 결제한 사용자
    converted = 0
    if yday_trial_expired > 0:
        expired_ids = [u.id for u in yday_trial_expired_qs.all()]
        if expired_ids:
            converted = (
                db.query(func.count(func.distinct(models.PaymentOrder.user_id)))
                .filter(
                    models.PaymentOrder.user_id.in_(expired_ids),
                    models.PaymentOrder.status == "CONFIRMED",
                    models.PaymentOrder.confirmed_at < end,
                )
                .scalar() or 0
            )
    conversion_rate = (converted / yday_trial_expired * 100) if yday_trial_expired else 0.0

    # ─── 4. AI 사용량 ──────────────────────────────────────
    yday_ai = (
        db.query(
            func.count(models.AIAnalysisLog.bid_no),
            func.coalesce(func.sum(models.AIAnalysisLog.token_usage), 0),
        )
        .filter(
            models.AIAnalysisLog.created_at >= start,
            models.AIAnalysisLog.created_at < end,
        )
        .one()
    )
    yday_ai_count, yday_tokens = yday_ai

    # gpt-4o-mini 비용 추정: 입력 $0.15/1M + 출력 $0.60/1M ≈ 평균 $0.40/1M
    # (실측 가격 변경 시 상수 조정)
    estimated_usd = (yday_tokens / 1_000_000) * 0.40
    estimated_krw = int(estimated_usd * 1380)  # 환율 가정

    # ─── 5. 자가보정 상태 ──────────────────────────────────
    autocal: dict[str, Any] = {}
    try:
        from app.services.autocalibrate.strategy_store import get_default_store
        store = get_default_store()
        active = store.load_active()
        autocal = {
            "active_version": active.version_id,
            "metrics": active.metrics or {},
            "created_at": active.created_at,
        }
    except Exception:
        autocal = {"active_version": None}

    # ─── 6. 시스템 헬스 ────────────────────────────────────
    pending_count = (
        db.query(func.count(models.PaymentOrder.id))
        .filter(models.PaymentOrder.status == "PENDING")
        .scalar() or 0
    )

    failed_today = (
        db.query(func.count(models.PaymentOrder.id))
        .filter(
            models.PaymentOrder.status == "FAILED",
            models.PaymentOrder.created_at >= start,
            models.PaymentOrder.created_at < end,
        )
        .scalar() or 0
    )

    # 최근 크롤 시각
    last_crawled = (
        db.query(func.max(models.OpeningResult.crawled_at)).scalar()
    )

    # ─── 7. 이상 알림 (휴리스틱 기반) ────────────────────────
    anomalies: list[str] = []

    # 결제 실패 폭증 (>5건/일)
    if failed_today > 5:
        anomalies.append(f"⚠️ 결제 실패 {failed_today}건 (평소 0~2건)")

    # PENDING 누적 (>10건)
    if pending_count > 10:
        anomalies.append(f"⚠️ PENDING 누적 {pending_count}건 — admin 에서 cleanup 권장")

    # AI 비용 급증 (어제 5,000원 초과 추정)
    if estimated_krw > 5000:
        anomalies.append(f"⚠️ AI 비용 {estimated_krw:,}원 추정 — 평소 대비 확인 필요")

    # 크롤러 정체 (마지막 크롤이 30시간+ 전)
    if last_crawled:
        gap_hours = (
            datetime.now(timezone.utc).replace(tzinfo=None) - last_crawled
        ).total_seconds() / 3600
        if gap_hours > 30:
            anomalies.append(f"⚠️ 크롤러 {gap_hours:.0f}시간째 정체 — 확인 필요")

    # ─── 요약 문자열 (이메일/슬랙 한 줄 헤더) ────────────────
    summary_line = (
        f"📊 {target.isoformat()} BidEasy 운영 리포트 — "
        f"매출 {yday_amount:,}원 ({yday_count}건) · "
        f"신규 {new_signups}명 · "
        f"전환율 {conversion_rate:.1f}% · "
        f"AI {yday_ai_count}회 (~{estimated_krw:,}원) · "
        f"이상 {len(anomalies)}건"
    )

    return {
        "target_date": target.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "revenue": {
            "yesterday_amount": int(yday_amount),
            "yesterday_count": int(yday_count),
            "month_to_date_amount": int(month_total or 0),
            "mrr_estimate": mrr_estimate,
            "active_pro": active_pro,
            "active_pro_plus": active_pro_plus,
        },
        "users": {
            "total": total_users,
            "new_signups": new_signups,
            "trial_active": trial_active,
        },
        "conversion": {
            "yday_trial_expired": yday_trial_expired,
            "yday_converted": converted,
            "conversion_rate_pct": round(conversion_rate, 1),
        },
        "ai_usage": {
            "yday_count": int(yday_ai_count),
            "yday_tokens": int(yday_tokens),
            "estimated_usd": round(estimated_usd, 4),
            "estimated_krw": estimated_krw,
        },
        "autocalibrate": autocal,
        "system_health": {
            "pending_payments": pending_count,
            "failed_today": failed_today,
            "last_crawled_at": last_crawled.isoformat() if last_crawled else None,
        },
        "anomalies": anomalies,
        "summary_line": summary_line,
    }


def format_report_as_markdown(report: dict[str, Any]) -> str:
    """슬랙·이메일 발송용 마크다운 포맷팅."""
    rev = report["revenue"]
    users = report["users"]
    conv = report["conversion"]
    ai = report["ai_usage"]
    sys_h = report["system_health"]
    anomalies = report["anomalies"]

    lines = [
        f"*📊 BidEasy 일일 리포트 — {report['target_date']}*",
        "",
        "*💰 매출*",
        f"• 어제: {rev['yesterday_amount']:,}원 ({rev['yesterday_count']}건)",
        f"• 이번 달 누적: {rev['month_to_date_amount']:,}원",
        f"• MRR 추정: {rev['mrr_estimate']:,}원 (Pro {rev['active_pro']} + Pro+ {rev['active_pro_plus']})",
        "",
        "*👤 사용자*",
        f"• 총 가입자: {users['total']}명",
        f"• 신규 가입: {users['new_signups']}명",
        f"• Trial 활성: {users['trial_active']}명",
        "",
        "*🎯 Trial → Pro 전환*",
        f"• 어제 Trial 만료: {conv['yday_trial_expired']}명",
        f"• 결제 전환: {conv['yday_converted']}명",
        f"• 전환율: {conv['conversion_rate_pct']}%",
        "",
        "*🤖 AI 사용*",
        f"• 어제 분석: {ai['yday_count']}회",
        f"• 토큰: {ai['yday_tokens']:,}",
        f"• 비용 추정: ${ai['estimated_usd']:.2f} (~{ai['estimated_krw']:,}원)",
        "",
        "*⚙️ 시스템*",
        f"• PENDING 결제: {sys_h['pending_payments']}건",
        f"• 어제 FAILED: {sys_h['failed_today']}건",
        f"• 마지막 크롤: {sys_h['last_crawled_at'] or '없음'}",
    ]

    if anomalies:
        lines.append("")
        lines.append("*🚨 이상 알림*")
        lines.extend([f"• {a}" for a in anomalies])

    autocal = report.get("autocalibrate") or {}
    if autocal.get("active_version"):
        lines.append("")
        lines.append("*🧠 자가보정*")
        lines.append(f"• Active: `{autocal['active_version']}`")
        metrics = autocal.get("metrics") or {}
        if metrics:
            lines.append(
                f"• 낙찰 {metrics.get('win_rate', 0)}% · "
                f"탈락 {metrics.get('dropout_rate', 0)}% · "
                f"통과 {metrics.get('pass_rate', 0)}%"
            )

    return "\n".join(lines)
