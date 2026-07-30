"""발송 금지 목록(suppression) — 반송·불만 자동 억제.

**발송 판정의 두 번째 관문이다.** 첫 관문인 `consent.py` 는 "보내도 되는가"(법적 자격)를
보고, 이 모듈은 "보내면 해가 되는가"(도달성·평판)를 본다. 둘은 성격이 다르므로 분리한다:

  - 동의는 광고성 정보에만 필요하고, 사용자가 철회하면 풀린다.
  - 억제는 **광고·거래를 가리지 않는다.** 없는 주소로 계속 쏘면 반송률이 오르고,
    AWS 는 반송률 5%·불만율 0.1% 초과 시 계정 발송을 정지시킨다. 그러면 결제·영수증
    같은 거래 메일까지 못 나간다. 즉 억제는 고객 보호가 아니라 **채널 자체를 지키는 장치**다.

일시 반송(Transient — 사서함 꽉 참, 일시 장애)은 억제하지 않는다. 영구 억제하면 정상
고객을 영구히 잃는다. 영구(Permanent) 반송과 불만(complaint)만 등록한다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import models

logger = get_logger(__name__)

REASON_BOUNCE = "bounce"
REASON_COMPLAINT = "complaint"
REASON_MANUAL = "manual"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize(email: Optional[str]) -> Optional[str]:
    """소문자·trim. 대소문자만 다른 같은 주소가 억제를 우회하지 못하게 한다."""
    if not email:
        return None
    norm = email.strip().lower()
    return norm or None


def get(db: Session, email: Optional[str]) -> Optional[models.EmailSuppression]:
    norm = normalize(email)
    if not norm:
        return None
    return (
        db.query(models.EmailSuppression)
        .filter(models.EmailSuppression.email == norm)
        .first()
    )


def is_suppressed(db: Session, email: Optional[str]) -> bool:
    return get(db, email) is not None


def suppress(
    db: Session,
    email: Optional[str],
    *,
    reason: str,
    source: str = "ses_sns",
    subtype: Optional[str] = None,
    detail: Optional[str] = None,
) -> Optional[models.EmailSuppression]:
    """주소를 발송 금지 목록에 올린다(멱등 — 이미 있으면 이벤트 횟수만 누적).

    커밋까지 수행한다: 웹훅 처리 중 예외가 나도 억제만은 남아야 하기 때문이다.
    """
    norm = normalize(email)
    if not norm:
        return None

    existing = get(db, norm)
    if existing:
        existing.event_count = (existing.event_count or 0) + 1
        existing.last_event_at = _utcnow()
        # 불만(complaint)은 반송보다 강한 신호라 사유를 덮어쓴다(반대 방향은 유지).
        if reason == REASON_COMPLAINT and existing.reason != REASON_COMPLAINT:
            existing.reason = reason
            existing.subtype = subtype
            existing.detail = (detail or "")[:300] or None
        db.commit()
        return existing

    row = models.EmailSuppression(
        email=norm,
        reason=reason,
        subtype=(subtype or None),
        source=source,
        detail=(detail or "")[:300] or None,
        event_count=1,
        last_event_at=_utcnow(),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # 동시 이벤트가 같은 주소를 넣은 경우 — 조회로 수렴
        db.rollback()
        return get(db, norm)
    logger.info("suppressed email reason=%s subtype=%s source=%s", reason, subtype, source)
    return row


def release(db: Session, email: Optional[str], *, source: str = "admin") -> bool:
    """억제 해제(오탐 구제용). 해제해도 수신동의는 복구되지 않는다 — 별개 판정이다."""
    row = get(db, email)
    if not row:
        return False
    db.delete(row)
    db.commit()
    logger.info("released suppression email=%s by=%s", normalize(email), source)
    return True
