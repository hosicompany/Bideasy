"""
리드 → 가입 전환 링크 서비스
============================
무료 자격 진단으로 남긴 Lead 가, 나중에 같은 이메일로 회원가입하면
그 전환을 기록한다(승리 이론 "안전에 지갑을 연다" 검증의 측정 고리).

설계 결정 (2026-07-18):
- **이메일 정규화(소문자·trim)로 매칭** — Lead 저장 시점엔 정규화가 전혀 없고
  (capture 는 raw str), User.email 도 EmailStr 형식검증만 하므로, 조회 시점에
  양쪽을 정규화해 비교한다.
- **동일 이메일 Lead 다건 링크** — capture 에 dedup 이 없어 한 이메일에 여러 row 가
  존재할 수 있다. 미전환(converted_user_id IS NULL) 전부를 전환 처리한다.
- **best-effort** — 이미 커밋된 가입 흐름 뒤에 호출하며, 어떤 실패도 삼켜서
  회원가입을 절대 막지 않는다.
"""

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models

logger = logging.getLogger(__name__)


def normalize_email(email: str | None) -> str | None:
    """소문자·trim 정규화. 빈 값은 None."""
    if not email:
        return None
    norm = email.strip().lower()
    return norm or None


def link_leads_to_user(db: Session, user: "models.User") -> int:
    """가입한 User 이메일과 일치하는 미전환 Lead 를 converted 로 링크.

    Returns:
        링크된 Lead 수 (실패·해당 없음 시 0).
    """
    norm = normalize_email(getattr(user, "email", None))
    user_id = getattr(user, "id", None)
    if not norm or not user_id:
        return 0

    try:
        leads = (
            db.query(models.Lead)
            .filter(
                func.lower(func.trim(models.Lead.email)) == norm,
                models.Lead.converted_user_id.is_(None),
            )
            .all()
        )
        for lead in leads:
            lead.converted_user_id = user_id
            lead.nurture_status = "converted"
        if leads:
            db.commit()
            logger.info(
                "lead conversion: linked %d lead(s) to user_id=%s", len(leads), user_id
            )
        return len(leads)
    except Exception:
        logger.exception("lead conversion linking failed for user_id=%s", user_id)
        try:
            db.rollback()
        except Exception:
            pass
        return 0
