"""수신거부(옵트아웃) — 로그인 없이 즉시 처리되는 공개 엔드포인트.

법과 실무가 같은 방향을 가리킨다: 해지가 어려우면 사용자는 대신 **스팸 신고**를 누르고,
그러면 도메인 평판이 떨어져 거래 메일까지 안 들어간다. 그래서 해지는 링크 한 번으로 끝난다.

경로 두 벌이 있는 이유:
  - `POST /unsubscribe?token=` : 실제 처리. 메일 클라이언트의 원클릭 해지(RFC 8058)도
    이 경로로 들어온다.
  - `GET /unsubscribe/status?token=` : 사람이 페이지에서 확인할 때 쓰는 조회.
GET 으로 상태를 바꾸지 않는 이유는, 메일 서버·보안 스캐너가 링크를 미리 열어보면서
사용자 의사와 무관하게 해지가 되는 것을 막기 위해서다(정적 페이지가 POST 를 호출한다).
"""
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.signed_token import InvalidSignedToken, parse_token
from app.db import models
from app.db.session import get_db
from app.services import consent as consent_service
from app.services import nurture
from app.services.nurture import UNSUB_PURPOSE

logger = get_logger(__name__)

router = APIRouter()

_MODELS = {"lead": models.Lead, "user": models.User}


def _mask(email: Optional[str]) -> Optional[str]:
    """부분 마스킹 — 본인 확인엔 충분하되 토큰 유출 시 주소가 통째로 새지 않게."""
    if not email or "@" not in email:
        return None
    name, _, domain = email.partition("@")
    head = name[:2] if len(name) > 2 else name[:1]
    return f"{head}{'*' * max(1, len(name) - len(head))}@{domain}"


def _resolve(db: Session, token: Optional[str]):
    try:
        subject_type, subject_id = parse_token(UNSUB_PURPOSE, token)
    except InvalidSignedToken:
        raise HTTPException(status_code=400, detail="링크가 올바르지 않아요. 메일의 링크를 다시 눌러 주세요.")

    model = _MODELS.get(subject_type)
    if model is None:
        raise HTTPException(status_code=400, detail="링크가 올바르지 않아요.")
    subject = db.get(model, subject_id)
    if subject is None:
        # 이미 삭제된 대상 — 사용자 입장에선 "더 이상 안 옴"이 참이므로 오류로 만들지 않는다.
        return subject_type, subject_id, None
    return subject_type, subject_id, subject


@router.get("/unsubscribe/status")
def unsubscribe_status(
    token: str = Query(..., description="메일에 담긴 서명 토큰"),
    db: Session = Depends(get_db),
):
    """해지 전 확인용 조회 — 상태를 바꾸지 않는다."""
    _stype, _sid, subject = _resolve(db, token)
    if subject is None:
        return {"valid": True, "email": None, "unsubscribed": True}
    return {
        "valid": True,
        "email": _mask(getattr(subject, "email", None)),
        "unsubscribed": not bool(getattr(subject, "marketing_consent", False)),
    }


@router.post("/unsubscribe")
def unsubscribe(
    request: Request,
    token: Optional[str] = Query(None),
    body_token: Optional[str] = Body(None, embed=True, alias="token"),
    db: Session = Depends(get_db),
):
    """수신거부 처리 — 멱등(이미 해지된 상태여도 200)."""
    subject_type, _sid, subject = _resolve(db, token or body_token)
    if subject is None:
        return {"ok": True, "email": None, "already": True}

    already = not bool(getattr(subject, "marketing_consent", False))
    if not already:
        consent_service.withdraw_marketing(
            db, subject, subject_type=subject_type, source="email_unsub",
            request=request, note="수신거부 링크",
        )
        db.commit()
        logger.info("unsubscribe: %s:%s", subject_type, getattr(subject, "id", None))
        _notify_result(db, subject, subject_type=subject_type)

    return {"ok": True, "email": _mask(getattr(subject, "email", None)), "already": already}


def _kst_label(dt: Optional[datetime]) -> str:
    """DB 의 naive UTC 를 사람이 읽는 KST 문자열로."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M") + " (KST)"


def _notify_result(db: Session, subject, *, subject_type: str) -> None:
    """수신거부 처리 결과 통지 — 법정 고지(정보통신망법 제50조).

    광고를 거부한 사람에게 보내는 메일이므로 **거래성**으로 보낸다. 동의 게이트를 타지
    않는 이유가 바로 이것이다 — 동의를 따지면 방금 철회한 사람에게는 영영 통지할 수 없다.

    best-effort: 통지 발송이 실패해도 **수신거부 처리는 되돌리지 않는다.** 해지가 안 되는
    것이 통지가 안 되는 것보다 훨씬 나쁘고, 해지 실패는 곧 스팸 신고로 이어진다.

    ⚠️ 억제 목록(반송·불만)에 오른 주소에는 nurture 가 이 통지도 막는다. 의도된 동작이다 —
    이미 스팸 신고를 눌렀거나 존재하지 않는 주소에 더 보내면 계정 발송 자체가 위험해진다.
    막힌 사실은 원장에 `skipped/suppressed` 로 남아 증적이 된다.
    """
    email = (getattr(subject, "email", None) or "").strip()
    if not email:
        return
    withdrawn_at = getattr(subject, "marketing_withdrawn_at", None)
    # 재동의 후 다시 철회하면 그때도 통지해야 하므로 키에 철회 시각을 넣는다.
    # 시각을 빼면 두 번째 철회의 통지가 '중복'으로 조용히 막힌다.
    # 마이크로초까지 쓰는 이유: 초 단위로 자르면 짧은 간격의 **서로 다른 철회**가 같은
    # 키로 뭉쳐 뒤엣것이 통지되지 않는다(법정 고지가 조용히 누락된다).
    stamp = withdrawn_at.strftime("%Y%m%d%H%M%S%f") if withdrawn_at else "na"
    recipient = hashlib.sha1(email.lower().encode("utf-8")).hexdigest()[:16]
    try:
        nurture.send_transactional(
            db, subject,
            subject_type=subject_type,
            template="unsub_result",
            ctx={"email": email, "processed_at": _kst_label(withdrawn_at)},
            dedupe_key=f"unsub_result:email:{recipient}:{stamp}",
        )
    except Exception as e:  # noqa: BLE001 — 해지 응답을 절대 막지 않는다
        db.rollback()
        logger.warning("unsub 결과 통지 실패(비치명적) %s:%s: %s",
                       subject_type, getattr(subject, "id", None), e)
