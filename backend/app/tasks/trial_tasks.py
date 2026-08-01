"""
체험(Trial) 만료 알림 Celery 태스크
=====================================
14일 Pro 체험 사용자에게 만료 임박·만료 알림을 자동 발송.

스케줄 (celery_app.py beat_schedule):
- 매일 10:00 KST: trial.send_expiry_reminders
  → 3일 후 만료 / 1일 후 만료 / 어제 만료된 사용자 식별 → Notification 생성

알림 종류:
- TRIAL_EXPIRING_SOON_3D (Pro 체험 3일 남음 — 결제 유도)
- TRIAL_EXPIRING_SOON_1D (Pro 체험 1일 남음 — 결제 유도)
- TRIAL_EXPIRED (만료됨 — Win-back 7일 한정 첫달 50% 할인)
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal
from app.schemas import subscription
from app.services import consent as consent_service
from app.services import nurture

# 한 회차에 처리할 회원 상한(폭주 방어). id 오름차순으로 자르므로 넘치면 로그로 알린다.
_MAX_USERS_PER_RUN = 2000

logger = get_logger(__name__)

KST = timezone(timedelta(hours=9))

# 윈백 문구의 숫자는 **상수에서 파생**시킨다. 메일에 값을 적어두면 가격 개편 때
# (2026-07 처럼) 조용히 거짓말이 된다 — 안내한 금액과 실제 청구액이 다르면 분쟁이다.
_WINBACK_GRACE_DAYS = subscription.WINBACK_GRACE_DAYS
_WINBACK_PRICE_LABEL = "{:,}원".format(
    subscription.MONTHLY_PRICES[subscription.TIER_PRO]
    * (100 - subscription.WINBACK_DISCOUNT_PCT)
    // 100
)


def _send_mail(db, user, template: str, ctx: dict, key: str) -> None:
    """체험 시퀀스 메일 1통 — 실패가 다른 사용자·인앱 알림을 막지 않는다.

    광고/거래 분기는 **템플릿 카테고리**가 결정한다. 여기서 대상을 자체 판단하지 않는
    이유는, 그러면 판정이 두 곳으로 갈라져 언젠가 미동의자에게 광고가 나가기 때문이다.
    광고 템플릿이면 `nurture` 가 동의 게이트에서 막고 `skipped/no_consent` 로 기록한다.
    """
    try:
        category = nurture.email_templates.category_of(template)
        send = nurture.send_marketing if category == "marketing" else nurture.send_transactional
        send(db, user, subject_type="user", template=template, ctx=ctx, dedupe_key=key)
    except Exception as e:  # noqa: BLE001 — 메일 1통 실패가 배치를 죽이지 않는다
        db.rollback()
        logger.warning("[trial] 메일 실패(건너뜀) user=%s template=%s: %s", user.id, template, e)


# 알림 제목·본문 템플릿
_TEMPLATES = {
    "TRIAL_EXPIRING_3D": (
        "Pro 체험이 3일 남았어요 🎁",
        "지금 결제하시면 첫 달 50% 할인 — Pro 19,900원 → 9,950원.",
    ),
    "TRIAL_EXPIRING_1D": (
        "Pro 체험이 내일 끝나요 ⏰",
        "AI 분석·Deep Analysis 등 Pro 기능이 일일 한도로 제한됩니다. 지금 결제 시 첫 달 50% 할인.",
    ),
    "TRIAL_EXPIRED": (
        "Pro 체험이 끝났습니다",
        "체험 만료 후 7일 이내 결제 시 첫 달 50% 할인 — 9,950원에 Pro 한 달 더 사용해보세요.",
    ),
}


def _has_notification(db, user_id: int, noti_type: str) -> bool:
    """동일 유형의 알림이 이미 있는지 — 중복 발송 방지."""
    exists = (
        db.query(models.Notification.id)
        .filter(
            models.Notification.user_id == user_id,
            models.Notification.noti_type == noti_type,
        )
        .first()
    )
    return exists is not None


def _create_trial_notification(db, user_id: int, noti_type: str) -> bool:
    """Notification 1건 생성. 이미 있으면 False, 새로 만들었으면 True."""
    if _has_notification(db, user_id, noti_type):
        return False

    title, body = _TEMPLATES[noti_type]
    noti = models.Notification(
        user_id=user_id,
        title=title,
        body=body,
        noti_type=noti_type,
        data_json={"trial_event": noti_type},
        is_read=0,
    )
    db.add(noti)
    return True


@celery_app.task(name="trial.send_onboarding_sequence")
def send_onboarding_sequence() -> dict:
    """체험 초반 광고 3종 — D1 매칭 / D3 익스텐션 / D7 가치 요약.

    **전부 광고 카테고리**라 동의·확인을 마친(`sendable_filter`) 회원에게만 나간다.
    만료 고지 같은 거래 안내는 `send_expiry_reminders` 가 전원에게 따로 보낸다 —
    즉 미동의자가 '체험이 끝난다'는 사실을 못 받는 일은 없다.

    D 계산은 `trial_started_at` 기준 **KST 달력일** 차이다. 시각 차로 하루가 밀리면
    D1 메일이 새벽에 가거나 건너뛰어진다(태스크는 매일 10:00 KST 1회 실행).
    """
    from app.services import lead_matching

    db = SessionLocal()
    results = {"d1": 0, "d3": 0, "d7": 0, "checked": 0, "errors": 0}
    try:
        today = datetime.now(timezone.utc).astimezone(KST).date()

        users = (
            db.query(models.User)
            .filter(models.User.trial_started_at.isnot(None))
            .filter(consent_service.sendable_filter(models.User))
            .filter(models.User.email.isnot(None), models.User.email != "")
            .order_by(models.User.id)
            .limit(_MAX_USERS_PER_RUN)
            .all()
        )
        if len(users) == _MAX_USERS_PER_RUN:
            logger.warning("[trial.onboarding] 회차 상한 %s 도달 — 이후 회원은 다음 회차로",
                           _MAX_USERS_PER_RUN)

        for u in users:
            results["checked"] += 1
            try:
                started = u.trial_started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                day = (today - started.astimezone(KST).date()).days

                if day == 1:
                    matched = lead_matching.match_notices(db, None, u.licenses, u.location)
                    if not matched:
                        continue          # 빈 목록 메일은 그 자체가 스팸이다
                    _send_mail(
                        db, u, "trial_daily_matches",
                        {
                            "matched_count": len(matched),
                            "capped": len(matched) >= lead_matching.MATCH_LIMIT,
                            "notices": [
                                {"title": n.title or "",
                                 "end_date_label": n.end_date.strftime("%m/%d") if n.end_date else ""}
                                for n in matched[:5]
                            ],
                        },
                        f"trial_daily_matches:user:{u.id}",
                    )
                    results["d1"] += 1
                elif day == 3:
                    _send_mail(db, u, "trial_extension_guide", {},
                               f"trial_extension_guide:user:{u.id}")
                    results["d3"] += 1
                elif day == 7:
                    # AIAnalysisLog 는 bid_no 기준 **캐시**라 사용자별 집계가 안 된다.
                    # 실제 사용 흔적은 UserBid(투찰 계산 기록)와 Favorite 이다.
                    checks = (
                        db.query(models.UserBid.id)
                        .filter(models.UserBid.user_id == u.id)
                        .count()
                    )
                    favorites = (
                        db.query(models.Favorite.id)
                        .filter(models.Favorite.user_id == u.id)
                        .count()
                    )
                    _send_mail(db, u, "trial_value_recap",
                               {"check_count": checks, "favorite_count": favorites},
                               f"trial_value_recap:user:{u.id}")
                    results["d7"] += 1
            except Exception as e:  # noqa: BLE001 — 1건 실패가 배치를 죽이지 않는다
                results["errors"] += 1
                db.rollback()
                logger.warning("[trial.onboarding] user=%s 실패(건너뜀): %s", u.id, e)

        db.commit()
        logger.info(f"[trial.send_onboarding_sequence] {results}")
        return results
    except Exception as e:
        db.rollback()
        logger.error(f"[trial.send_onboarding_sequence] error: {e}", exc_info=True)
        return {"error": str(e), **results}
    finally:
        db.close()


@celery_app.task(name="trial.send_expiry_reminders")
def send_expiry_reminders() -> dict:
    """
    매일 10:00 KST 실행. 활성 체험 사용자 중:
      - 정확히 3일 후 만료 → TRIAL_EXPIRING_3D
      - 정확히 1일 후 만료 → TRIAL_EXPIRING_1D
      - 어제 만료 (만료 후 0~1일) → TRIAL_EXPIRED

    중복 방지: 같은 noti_type 알림이 이미 있으면 건너뜀.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        today_start_kst = now.astimezone(KST).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        three_days_start = (today_start_kst + timedelta(days=3)).astimezone(timezone.utc)
        three_days_end = three_days_start + timedelta(days=1)
        one_day_start = (today_start_kst + timedelta(days=1)).astimezone(timezone.utc)
        one_day_end = one_day_start + timedelta(days=1)
        yesterday_start = (today_start_kst - timedelta(days=1)).astimezone(timezone.utc)
        yesterday_end = yesterday_start + timedelta(days=1)

        results = {"3d": 0, "1d": 0, "expired": 0, "skipped": 0}

        # ── 3일 후 만료 사용자 ──────────────────────────────
        users_3d = (
            db.query(models.User)
            .filter(
                models.User.trial_expires_at.isnot(None),
                models.User.trial_expires_at >= three_days_start,
                models.User.trial_expires_at < three_days_end,
                # 유료 구독자는 알림 제외
                or_(
                    models.User.subscription_expires_at.is_(None),
                    models.User.subscription_expires_at < now,
                ),
                models.User.tier == "free",
            )
            .all()
        )
        for u in users_3d:
            if _create_trial_notification(db, u.id, "TRIAL_EXPIRING_3D"):
                results["3d"] += 1
                # 만료 '사실' 고지는 거래 — 동의와 무관하게 전원에게. 할인은 넣지 않는다.
                _send_mail(db, u, "trial_expiry", {"days_left": 3},
                           f"trial_expiry:user:{u.id}:d3")
            else:
                results["skipped"] += 1

        # ── 1일 후 만료 사용자 ──────────────────────────────
        users_1d = (
            db.query(models.User)
            .filter(
                models.User.trial_expires_at.isnot(None),
                models.User.trial_expires_at >= one_day_start,
                models.User.trial_expires_at < one_day_end,
                or_(
                    models.User.subscription_expires_at.is_(None),
                    models.User.subscription_expires_at < now,
                ),
                models.User.tier == "free",
            )
            .all()
        )
        for u in users_1d:
            if _create_trial_notification(db, u.id, "TRIAL_EXPIRING_1D"):
                results["1d"] += 1
                _send_mail(db, u, "trial_expiry", {"days_left": 1},
                           f"trial_expiry:user:{u.id}:d1")
            else:
                results["skipped"] += 1

        # ── 어제 만료된 사용자 (Win-back) ───────────────────
        users_expired = (
            db.query(models.User)
            .filter(
                models.User.trial_expires_at.isnot(None),
                models.User.trial_expires_at >= yesterday_start,
                models.User.trial_expires_at < yesterday_end,
                or_(
                    models.User.subscription_expires_at.is_(None),
                    models.User.subscription_expires_at < now,
                ),
                models.User.tier == "free",
            )
            .all()
        )
        for u in users_expired:
            if _create_trial_notification(db, u.id, "TRIAL_EXPIRED"):
                results["expired"] += 1
                # 만료 사실은 거래로 이미 알렸다(D-1). 여기서 보내는 건 **할인 안내**라
                # 광고이고, 동의자에게만 나간다. 미동의자도 만료 사실은 이미 알고 있다.
                _send_mail(
                    db, u, "trial_winback",
                    {"discount_price": _WINBACK_PRICE_LABEL, "grace_days": _WINBACK_GRACE_DAYS},
                    f"trial_winback:user:{u.id}",
                )
            else:
                results["skipped"] += 1

        db.commit()
        logger.info(f"[trial.send_expiry_reminders] {results}")
        return results
    except Exception as e:
        db.rollback()
        logger.error(f"[trial.send_expiry_reminders] error: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
