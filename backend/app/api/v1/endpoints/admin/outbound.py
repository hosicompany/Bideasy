"""
관리자 아웃바운드 발송 운영 API
================================
발송은 사람 눈에 안 보이는 곳에서 일어나므로, "지금 켜져 있나 / 무엇이 나갔나 /
왜 안 나갔나"를 확인할 창구가 필요하다.

Endpoints:
- GET  /admin/outbound            — 발송 원장(최근순) + 상태·사유 집계 + 킬스위치 상태
- GET  /admin/outbound/preview    — 템플릿 렌더 미리보기(전송 없음)
- POST /admin/outbound/test-send  — 관리자 **본인 계정**으로 실제 경로 발송(게이트 그대로)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_admin
from app.db import models
from app.db.session import get_db
from app.services import email_templates, nurture

router = APIRouter()


@router.get("/outbound")
def outbound_log(
    status: Optional[str] = Query(None, description="sent | dry_run | skipped | failed"),
    template: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """발송 원장 + 집계. skipped 사유가 쌓이면 게이트가 어디서 막는지 바로 보인다."""
    q = db.query(models.OutboundMessage)
    if status:
        q = q.filter(models.OutboundMessage.status == status)
    if template:
        q = q.filter(models.OutboundMessage.template == template)

    total = q.count()
    rows = (
        q.order_by(models.OutboundMessage.created_at.desc(), models.OutboundMessage.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    status_rows = (
        db.query(models.OutboundMessage.status, func.count(models.OutboundMessage.id))
        .group_by(models.OutboundMessage.status)
        .all()
    )
    reason_rows = (
        db.query(models.OutboundMessage.reason, func.count(models.OutboundMessage.id))
        .filter(models.OutboundMessage.reason.isnot(None))
        .group_by(models.OutboundMessage.reason)
        .all()
    )

    return {
        # 킬스위치가 꺼져 있으면 status 는 전부 dry_run 이다 — 오판 방지용으로 함께 반환.
        "outbound_enabled": settings.OUTBOUND_EMAIL_ENABLED,
        "from_email": settings.SES_FROM_EMAIL,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "by_status": [{"status": s, "count": int(c)} for s, c in status_rows],
        "by_reason": [{"reason": r, "count": int(c)} for r, c in reason_rows],
        "items": [
            {
                "id": m.id,
                "subject_type": m.subject_type,
                "subject_id": m.subject_id,
                "email": m.email,
                "template": m.template,
                "category": m.category,
                "subject": m.subject,
                "status": m.status,
                "reason": m.reason,
                "provider_message_id": m.provider_message_id,
                "error": m.error,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ],
    }


@router.get("/outbound/preview")
def outbound_preview(
    template: str = Query(..., description="템플릿 이름 (예: lead_welcome)"),
    _admin=Depends(require_admin),
):
    """템플릿 렌더 미리보기 — 전송하지 않는다. 문구·법정 표기 확인용."""
    sample = {"region": "부산광역시", "industry": "전기공사", "matched_count": 12, "days_left": 3}
    try:
        rendered = email_templates.render(
            template, sample, unsubscribe_url=f"{settings.PUBLIC_WEB_URL}/unsubscribe?t=SAMPLE"
        )
    except email_templates.UnknownTemplate:
        raise HTTPException(status_code=404, detail=f"알 수 없는 템플릿: {template}")
    return {
        "template": template,
        "category": email_templates.category_of(template),
        "subject": rendered.subject,
        "text": rendered.text,
        "html": rendered.html,
    }


@router.post("/outbound/test-send")
def outbound_test_send(
    template: str = Query(..., description="템플릿 이름"),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """관리자 **본인 계정**으로 실제 발송 경로를 태운다(임의 주소 발송 불가).

    게이트를 우회하지 않는다 — 광고 템플릿인데 본인이 미동의면 skipped 가 나오는 것이
    정상이며, 그것이 곧 게이트가 살아 있다는 증거다.
    """
    try:
        category = email_templates.category_of(template)
    except email_templates.UnknownTemplate:
        raise HTTPException(status_code=404, detail=f"알 수 없는 템플릿: {template}")

    ctx = {"region": "부산광역시", "industry": "전기공사", "matched_count": 12, "days_left": 3}
    send = nurture.send_marketing if category == "marketing" else nurture.send_transactional
    row = send(db, admin, subject_type="user", template=template, ctx=ctx)
    return {
        "status": row.status,
        "reason": row.reason,
        "subject": row.subject,
        "to": row.email,
        "outbound_enabled": settings.OUTBOUND_EMAIL_ENABLED,
    }
