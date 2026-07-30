"""
관리자 동의 증적 조회 API
==========================
정보통신망법 제50조는 수신동의 사실의 **증명책임을 전송자에게** 지운다. 민원·분쟁이
들어왔을 때 "이 연락처는 언제·어디서·무슨 문구에 동의했는가"를 즉시 꺼낼 수 있어야
한다. 그 조회 창구가 이 모듈이다.

Endpoints:
- GET /admin/consents          — 증적 검색(연락처·주체·목적·행위별, 최근순)
- GET /admin/consents/summary  — 발송 가능 대상 수 + 동의/철회 집계
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.db import models
from app.db.session import get_db
from app.services import consent as consent_service

router = APIRouter()


def _row(rec: models.ConsentRecord) -> dict:
    return {
        "id": rec.id,
        "subject_type": rec.subject_type,
        "subject_id": rec.subject_id,
        "email": rec.email,
        "phone": rec.phone,
        "purpose": rec.purpose,
        "action": rec.action,
        "channel": rec.channel,
        "text_version": rec.text_version,
        "text_hash": rec.text_hash,
        "source": rec.source,
        "ip": rec.ip,
        "user_agent": rec.user_agent,
        "note": rec.note,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


@router.get("/consents")
def list_consents(
    q: Optional[str] = Query(None, description="이메일/휴대폰 부분일치"),
    subject_type: Optional[str] = Query(None, description="lead | user"),
    purpose: Optional[str] = Query(None, description="privacy | marketing"),
    action: Optional[str] = Query(None, description="grant | withdraw | reconfirm"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """동의·철회 증적 검색 (최근순). 증적은 추가 전용이라 수정·삭제 API 는 없다."""
    query = db.query(models.ConsentRecord)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(models.ConsentRecord.email.ilike(like), models.ConsentRecord.phone.ilike(like))
        )
    if subject_type:
        query = query.filter(models.ConsentRecord.subject_type == subject_type)
    if purpose:
        query = query.filter(models.ConsentRecord.purpose == purpose)
    if action:
        query = query.filter(models.ConsentRecord.action == action)

    total = query.count()
    rows = (
        query.order_by(models.ConsentRecord.created_at.desc(), models.ConsentRecord.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"total": int(total), "limit": limit, "offset": offset, "items": [_row(r) for r in rows]}


@router.get("/consents/summary")
def consent_summary(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """발송 가능 대상 규모 — 아웃바운드 가동 전 "누구에게 보낼 수 있나"의 정답지.

    sendable 은 동의 True·철회 없음·2년 내 확인을 모두 만족하는 수(발송 코드와 동일 기준).
    """
    def _counts(model, subject_type: str) -> dict:
        total = db.query(func.count(model.id)).scalar() or 0
        consented = (
            db.query(func.count(model.id))
            .filter(model.marketing_consent.is_(True))
            .scalar()
            or 0
        )
        withdrawn = (
            db.query(func.count(model.id))
            .filter(model.marketing_withdrawn_at.isnot(None))
            .scalar()
            or 0
        )
        sendable = (
            db.query(func.count(model.id))
            .filter(consent_service.sendable_filter(model))
            .scalar()
            or 0
        )
        return {
            "subject_type": subject_type,
            "total": int(total),
            "marketing_consented": int(consented),
            "withdrawn": int(withdrawn),
            "sendable": int(sendable),
            "consent_pct": round(consented / total * 100, 1) if total else 0.0,
        }

    action_rows = (
        db.query(
            models.ConsentRecord.purpose,
            models.ConsentRecord.action,
            func.count(models.ConsentRecord.id).label("count"),
        )
        .group_by(models.ConsentRecord.purpose, models.ConsentRecord.action)
        .all()
    )

    return {
        "leads": _counts(models.Lead, "lead"),
        "users": _counts(models.User, "user"),
        "records": [
            {"purpose": r.purpose, "action": r.action, "count": int(r.count or 0)}
            for r in action_rows
        ],
        "current_versions": consent_service.CURRENT_VERSION,
        "revalidate_days": consent_service.REVALIDATE_DAYS,
    }
