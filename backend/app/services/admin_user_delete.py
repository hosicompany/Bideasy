"""
관리자 — 안전한 사용자 cascade 삭제
======================================
오늘(2026-05-28) 운영 환경에서 user 직접 DELETE 시도 → point_transactions
FK 제약 RESTRICT 위반 발생. 그 경험을 코드로 구조화.

정책:
- 5개 종속 테이블 → DELETE (Notification, DeviceToken, UserBid,
  PointTransaction, Favorite)
- PaymentOrder → user_id SET NULL (회계·세무 분쟁 증거 보존)
- 활성 구독자 (force=False) → 409 거부 (먼저 환불 처리 안내)

사용처: /admin/users/{id} DELETE 엔드포인트.
직접 `db.delete(user)` 호출 금지 → 항상 이 헬퍼 경유.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db import models


def _has_active_paid_subscription(db: Session, user_id: int) -> bool:
    """유료 구독이 만료되지 않았는지 검사."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or user.tier == "free":
        return False
    exp = user.subscription_expires_at
    if exp is None:
        return True  # 무기한 → 활성
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > datetime.now(timezone.utc)


def delete_user_cascade(db: Session, user_id: int, force: bool = False) -> dict:
    """사용자 + 종속 데이터를 단일 트랜잭션으로 삭제.

    Args:
        db: SQLAlchemy Session (호출자가 commit 책임)
        user_id: 대상 사용자 id
        force: True 면 활성 구독 검사 건너뜀 (운영자가 명시적으로 위험 인지)

    Returns:
        { "user_id": id, "deleted": { "notifications": n, ... },
          "payment_orders_nullified": n }

    Raises:
        HTTPException 404: 사용자 없음
        HTTPException 409: 활성 구독 (force=False 시)
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, detail="사용자를 찾을 수 없어요")

    if not force and _has_active_paid_subscription(db, user_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "활성 유료 구독이 있어요. 먼저 결제 환불 처리 후 삭제하거나, "
                "force=true 옵션으로 강제 삭제하세요."
            ),
        )

    deleted = {}

    # 1. 알림
    deleted["notifications"] = db.query(models.Notification).filter(
        models.Notification.user_id == user_id
    ).delete(synchronize_session=False)

    # 2. 기기 토큰 (FCM)
    deleted["device_tokens"] = db.query(models.DeviceToken).filter(
        models.DeviceToken.user_id == user_id
    ).delete(synchronize_session=False)

    # 3. 입찰 기록
    deleted["user_bids"] = db.query(models.UserBid).filter(
        models.UserBid.user_id == user_id
    ).delete(synchronize_session=False)

    # 4. 포인트 거래 (오늘 발견된 FK 충돌의 핵심)
    deleted["point_transactions"] = db.query(models.PointTransaction).filter(
        models.PointTransaction.user_id == user_id
    ).delete(synchronize_session=False)

    # 5. 결제 주문 → user_id NULL (회계 기록 보존)
    payment_orders_nullified = db.query(models.PaymentOrder).filter(
        models.PaymentOrder.user_id == user_id
    ).update({"user_id": None}, synchronize_session=False)

    # 6. User
    db.delete(user)

    return {
        "user_id": user_id,
        "email": user.email,
        "deleted": deleted,
        "payment_orders_nullified": payment_orders_nullified,
    }
