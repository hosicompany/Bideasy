"""더블 옵트인 확인 — 로그인 없이 수신 시작을 확정하는 공개 엔드포인트.

왜 필요한가
-----------
`/leads/capture` 와 `/auth/register` 는 **인증도 이메일 소유 확인도 없다.** 요청 본문의
`marketing_consent: true` 만 믿고 광고를 보내면, 남의 주소를 적어 넣은 요청이 그대로
제3자에게 보내는 광고가 된다. 우리가 가진 증적은 제출자의 IP·UA 일 뿐 **주소 소유자의
동의가 아니다**(정보통신망법 §50 의 증명책임은 전송자에게 있다).

그래서 동의 시점에는 `marketing_confirmed_at` 을 비워 두고(= `sendable_filter` 가 광고를
막는다), 주소 소유자가 이 링크를 눌러야 발송 대상이 된다.

경로 두 벌인 이유는 수신거부와 같다:
  - `GET /optin/status` : 조회. 상태를 바꾸지 않는다.
  - `POST /optin`       : 실제 확정.
GET 으로 확정하면 메일 서버·보안 스캐너의 링크 프리페치가 사용자 대신 눌러 더블 옵트인이
무의미해진다(정적 페이지가 POST 를 호출한다).
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.signed_token import InvalidSignedToken, parse_token
from app.db import models
from app.db.session import get_db
from app.services import consent as consent_service
from app.services.nurture import OPTIN_PURPOSE

logger = get_logger(__name__)

router = APIRouter()

_MODELS = {"lead": models.Lead, "user": models.User}


def _resolve(db: Session, token: Optional[str]):
    try:
        subject_type, subject_id = parse_token(OPTIN_PURPOSE, token)
    except InvalidSignedToken:
        raise HTTPException(status_code=400, detail="링크가 올바르지 않아요. 메일의 링크를 다시 눌러 주세요.")

    model = _MODELS.get(subject_type)
    if model is None:
        raise HTTPException(status_code=400, detail="링크가 올바르지 않아요.")
    subject = db.get(model, subject_id)
    if subject is None:
        raise HTTPException(status_code=400, detail="링크가 만료됐어요. 다시 신청해 주세요.")
    return subject_type, subject


@router.get("/optin/status")
def optin_status(token: str = Query(...), db: Session = Depends(get_db)):
    """확인 전 조회 — 상태를 바꾸지 않는다."""
    _stype, subject = _resolve(db, token)
    return {
        "valid": True,
        "confirmed": consent_service.can_send_marketing(subject),
        "region": getattr(subject, "region", None) or getattr(subject, "location", None),
        "industry": getattr(subject, "industry", None),
    }


@router.post("/optin")
def optin_confirm(
    request: Request,
    token: Optional[str] = Query(None),
    body_token: Optional[str] = Body(None, embed=True, alias="token"),
    db: Session = Depends(get_db),
):
    """수신 신청 확인 — 이 시점부터 광고 발송 대상이 된다(멱등)."""
    subject_type, subject = _resolve(db, token or body_token)

    already = consent_service.can_send_marketing(subject)
    if not already:
        rec = consent_service.confirm_marketing(
            db, subject, subject_type=subject_type, source="email_optin", request=request,
        )
        if rec is None:
            # 철회했거나 동의 자체가 없는 대상 — 확인으로 되살리지 않는다.
            raise HTTPException(status_code=400, detail="수신 신청 내역이 없어요. 다시 신청해 주세요.")
        db.commit()
        db.refresh(subject)
        logger.info("optin confirmed: %s:%s", subject_type, getattr(subject, "id", None))
        _after_confirm(db, subject_type, subject)

    return {"ok": True, "already": already}


def _after_confirm(db: Session, subject_type: str, subject) -> None:
    """확인 직후 첫 메일 — 대상 종류에 따라 다르다.

    회원에게 체험 시작 안내(거래)를 여기서 보내는 이유: 가입 응답 경로에서 메일을
    **1통으로 줄이기 위해서**다. 가입은 퍼널의 목이라 SES 호출이 늘수록 504 위험이
    커진다. 동의자는 가입 시 확인 메일만 받고, 웰컴은 확인을 누른 이 시점에 받는다.

    여기서 실패해도 **확인 자체는 되돌리지 않는다.** 확인이 안 된 것으로 처리하면
    사용자는 링크를 눌렀는데도 아무 일이 없는 상태에 갇힌다.
    """
    if subject_type == "lead":
        from app.api.v1.endpoints.leads import send_welcome

        send_welcome(db, subject)
    elif subject_type == "user":
        from app.api.v1.endpoints.auth import _send_trial_welcome

        _send_trial_welcome(db, subject)
