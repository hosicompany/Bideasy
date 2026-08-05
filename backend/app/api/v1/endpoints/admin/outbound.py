"""
관리자 아웃바운드 발송 운영 API
================================
발송은 사람 눈에 안 보이는 곳에서 일어나므로, "지금 켜져 있나 / 무엇이 나갔나 /
왜 안 나갔나"를 확인할 창구가 필요하다.

Endpoints:
- GET  /admin/outbound            — 발송 원장(최근순) + 상태·사유 집계 + 킬스위치 상태
- GET  /admin/outbound/templates  — 등록된 템플릿 목록(이름·카테고리)
- GET  /admin/outbound/preview    — 템플릿 렌더 미리보기(전송 없음)
- POST /admin/outbound/test-send  — 관리자 **본인 계정**으로 실제 경로 발송(게이트 그대로)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_admin
from app.db import models
from app.db.session import get_db
from app.services import email_templates, lead_matching, nurture, suppression

router = APIRouter()

# 미리보기 본문에 나열할 공고 수 — 실제 발송(`nurture_tasks._LIST_N`)과 같은 눈높이.
_PREVIEW_NOTICE_N = 5


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


@router.get("/outbound/suppressions")
def list_suppressions(
    q: Optional[str] = Query(None, description="이메일 부분일치"),
    reason: Optional[str] = Query(None, description="bounce | complaint | manual"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """발송 금지 목록. 반송·불만이 쌓이는 속도가 도달성의 조기 경보다."""
    query = db.query(models.EmailSuppression)
    if q:
        query = query.filter(models.EmailSuppression.email.ilike(f"%{q.strip().lower()}%"))
    if reason:
        query = query.filter(models.EmailSuppression.reason == reason)

    total = query.count()
    rows = (
        query.order_by(models.EmailSuppression.created_at.desc(), models.EmailSuppression.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    reason_rows = (
        db.query(models.EmailSuppression.reason, func.count(models.EmailSuppression.id))
        .group_by(models.EmailSuppression.reason)
        .all()
    )
    return {
        "total": int(total),
        "by_reason": [{"reason": r, "count": int(c)} for r, c in reason_rows],
        "items": [
            {
                "id": s.id,
                "email": s.email,
                "reason": s.reason,
                "subtype": s.subtype,
                "source": s.source,
                "detail": s.detail,
                "event_count": s.event_count,
                "last_event_at": s.last_event_at.isoformat() if s.last_event_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in rows
        ],
    }


@router.post("/outbound/suppressions")
def add_suppression(
    email: str = Query(..., description="발송 금지할 주소"),
    detail: Optional[str] = Query(None, description="사유 메모"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """수동 억제(고객이 전화·카톡으로 거부 의사를 밝힌 경우 등)."""
    row = suppression.suppress(
        db, email, reason=suppression.REASON_MANUAL, source="admin", detail=detail
    )
    if row is None:
        raise HTTPException(status_code=400, detail="이메일 형식이 올바르지 않습니다.")
    return {"ok": True, "email": row.email, "reason": row.reason}


@router.delete("/outbound/suppressions")
def release_suppression(
    email: str = Query(..., description="해제할 주소"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """오탐 구제. **억제 해제가 수신동의를 복구하지는 않는다**(별개 판정)."""
    released = suppression.release(db, email, source="admin")
    if not released:
        raise HTTPException(status_code=404, detail="억제 목록에 없는 주소입니다.")
    return {"ok": True, "released": suppression.normalize(email)}


def _preview_ctx(db: Session, template: str) -> dict:
    """템플릿이 읽는 키를 빠짐없이 채운 ctx. 공고 목록은 **실제 공고**로 갈아끼운다.

    예전에는 모든 템플릿이 고정 ctx 하나(`region`/`industry`/`matched_count`/`days_left`)를
    돌려썼다. 그래서 공고 목록·확인 링크를 읽는 템플릿은 알맹이가 빈 채로 렌더돼,
    정작 점검이 필요한 부분(공고 링크가 열리는가)을 미리보기로 볼 수 없었다.

    가짜 공고번호로는 `/bid/{no}` 가 404 라 링크를 눌러 확인할 수 없으므로, DB 에
    활성 공고가 있으면 그것으로 채운다(빈 DB 면 정적 표본 그대로 — 레이아웃은 보인다).
    """
    ctx = email_templates.sample_ctx(template)
    if "notices" not in ctx:
        return ctx

    # 발송 배치와 같은 판정 경로. 표본 조건에 맞는 활성 공고가 없으면 조건을 풀어서라도
    # 실제 공고를 쓴다 — 미리보기의 목적은 자격 판정이 아니라 **링크·레이아웃 점검**이다.
    matched = lead_matching.match_notices(db, ctx.get("industry"), None, ctx.get("region"))
    if not matched:
        matched = (
            db.query(models.Notice)
            .filter(~models.Notice.title.like("[Mock]%"))
            .filter(models.Notice.end_date > datetime.now())
            .order_by(models.Notice.end_date.asc())
            .limit(lead_matching.MATCH_LIMIT)
            .all()
        )
    if not matched:
        return ctx

    ctx["notices"] = [lead_matching.notice_brief(n) for n in matched[:_PREVIEW_NOTICE_N]]
    # 본문의 "N건"과 나열된 목록이 어긋나면 미리보기로 문구를 판단할 수 없다.
    for key in ("new_count", "matched_count"):
        if key in ctx:
            ctx[key] = len(matched)
    ctx["capped"] = len(matched) >= lead_matching.MATCH_LIMIT
    return ctx


@router.get("/outbound/templates")
def outbound_templates(_admin=Depends(require_admin)):
    """등록된 템플릿 목록 — 미리보기/테스트 발송에 넣을 이름을 찾는 용도."""
    return {
        "items": [
            {"template": name, "category": email_templates.category_of(name)}
            for name in email_templates.template_names()
        ]
    }


@router.get("/outbound/preview")
def outbound_preview(
    template: str = Query(..., description="템플릿 이름 (예: lead_welcome)"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """템플릿 렌더 미리보기 — 전송하지 않는다. 문구·법정 표기·링크 확인용."""
    try:
        ctx = _preview_ctx(db, template)
        rendered = email_templates.render(
            template, ctx, unsubscribe_url=f"{settings.PUBLIC_WEB_URL}/unsubscribe?t=SAMPLE"
        )
    except email_templates.UnknownTemplate:
        raise HTTPException(status_code=404, detail=f"알 수 없는 템플릿: {template}")
    return {
        "template": template,
        "category": email_templates.category_of(template),
        "ctx": ctx,          # 무엇을 넣어 렌더했는지 — 빈칸의 원인을 바로 짚을 수 있다
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

    ctx 는 미리보기와 **같은 것**을 쓴다(`_preview_ctx`) — 미리보기에서 본 화면과 받은
    메일이 다르면 둘 중 무엇을 믿어야 할지 알 수 없다.
    """
    try:
        category = email_templates.category_of(template)
    except email_templates.UnknownTemplate:
        raise HTTPException(status_code=404, detail=f"알 수 없는 템플릿: {template}")

    ctx = _preview_ctx(db, template)
    send = nurture.send_marketing if category == "marketing" else nurture.send_transactional
    row = send(db, admin, subject_type="user", template=template, ctx=ctx)
    return {
        "status": row.status,
        "reason": row.reason,
        "subject": row.subject,
        "to": row.email,
        "notice_count": len(ctx.get("notices") or []),
        "outbound_enabled": settings.OUTBOUND_EMAIL_ENABLED,
    }
