"""SES 반송·불만 이벤트 수신 웹훅 (SNS → 자동 억제).

발송은 켰는데 이게 없으면 무슨 일이 벌어지는가: 없는 주소로 계속 쏘고, 스팸 신고를 받은
사람에게 또 보낸다. AWS 는 반송률 5%·불만율 0.1% 를 넘기면 계정 발송을 정지시키고, 그러면
결제·영수증 같은 거래 메일까지 막힌다. **그래서 시퀀스를 돌리기 전에 이 배관이 먼저다.**

설계 결정
- **인증 없이 열되 서명으로 막는다** — SNS 는 우리 토큰을 모른다. 대신 `sns_verify` 가
  AWS 서명·인증서 출처·TopicArn 을 검증한다(검증 없으면 누구나 가짜 반송으로 임의 고객을
  발송 금지로 만들 수 있다).
- **항상 2xx 로 답한다**(검증 실패만 403) — 5xx 를 주면 SNS 가 같은 메시지를 계속 재시도하고,
  처리 못 하는 이벤트 하나가 무한 재시도로 남는다. 우리가 모르는 이벤트 타입은 기록만 하고 넘긴다.
- **일시 반송은 억제하지 않는다** — 사서함 꽉 참·일시 장애까지 영구 차단하면 정상 고객을 잃는다.
- **불만(complaint)은 수신거부 의사로 취급** — 스팸 신고한 사람에게 "동의는 유효하다"고
  버티는 건 법(정보통신망법 취지)과 상식 모두에 어긋난다. 마케팅 동의를 즉시 철회 처리한다.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import models
from app.db.session import get_db
from app.services import consent as consent_service
from app.services import sns_verify, suppression

logger = get_logger(__name__)

router = APIRouter()

# SES 반송 유형 중 영구 실패 — 이것만 억제한다(Transient/Undetermined 는 제외)
_PERMANENT_BOUNCE = "Permanent"


def _emails_from(recipients: list) -> list[str]:
    out = []
    for r in recipients or []:
        addr = r.get("emailAddress") if isinstance(r, dict) else r
        if addr:
            out.append(addr)
    return out


def _withdraw_consent_for(db: Session, email: str, note: str) -> None:
    """불만 신고자의 마케팅 동의를 철회 처리(Lead·User 양쪽, 증적 남김)."""
    norm = suppression.normalize(email)
    if not norm:
        return
    for model, subject_type in ((models.Lead, "lead"), (models.User, "user")):
        rows = (
            db.query(model)
            .filter(model.email.isnot(None))
            .filter(model.marketing_consent.is_(True))
            .all()
        )
        for row in rows:
            if suppression.normalize(row.email) != norm:
                continue
            consent_service.withdraw_marketing(
                db, row, subject_type=subject_type, source="ses_complaint", note=note
            )
    db.commit()


def _handle_bounce(db: Session, message: dict) -> dict:
    bounce = message.get("bounce") or {}
    btype = bounce.get("bounceType")
    subtype = f"{btype}/{bounce.get('bounceSubType')}"
    emails = _emails_from(bounce.get("bouncedRecipients"))

    if btype != _PERMANENT_BOUNCE:
        # 일시 반송은 기록만 — 영구 차단하면 정상 고객을 잃는다.
        logger.info("transient bounce 무시 subtype=%s recipients=%d", subtype, len(emails))
        return {"handled": "bounce", "suppressed": 0, "transient": True}

    count = 0
    for email in emails:
        diag = ""
        for r in bounce.get("bouncedRecipients") or []:
            if r.get("emailAddress") == email:
                diag = r.get("diagnosticCode") or ""
                break
        if suppression.suppress(
            db, email, reason=suppression.REASON_BOUNCE, source="ses_sns",
            subtype=subtype, detail=diag,
        ):
            count += 1
    return {"handled": "bounce", "suppressed": count, "transient": False}


def _handle_complaint(db: Session, message: dict) -> dict:
    complaint = message.get("complaint") or {}
    subtype = complaint.get("complaintFeedbackType") or "unknown"
    emails = _emails_from(complaint.get("complainedRecipients"))

    count = 0
    for email in emails:
        if suppression.suppress(
            db, email, reason=suppression.REASON_COMPLAINT, source="ses_sns",
            subtype=subtype, detail=f"complaint feedback={subtype}",
        ):
            count += 1
        # 스팸 신고 = 수신거부 의사. 동의를 즉시 철회하고 증적을 남긴다.
        try:
            _withdraw_consent_for(db, email, note=f"SES complaint({subtype})")
        except Exception:
            logger.exception("complaint 동의 철회 실패(억제는 유지됨)")
            db.rollback()
    return {"handled": "complaint", "suppressed": count}


@router.post("/webhooks/ses")
async def ses_events(request: Request, db: Session = Depends(get_db)):
    """SNS → SES 이벤트 수신. 서명 검증 실패는 403, 그 외는 항상 2xx."""
    raw = await request.body()
    try:
        # SNS 는 Content-Type 을 text/plain 으로 보낼 때가 있어 직접 파싱한다.
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("dict 아님")
    except Exception:
        logger.warning("SES 웹훅: 본문 파싱 실패")
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    try:
        sns_verify.verify(payload)
    except sns_verify.SnsVerificationError as exc:
        # 여기서 통과시키면 누구나 임의 주소를 발송 금지로 만들 수 있다.
        logger.warning("SES 웹훅 서명 검증 실패: %s", exc)
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    msg_type = payload.get("Type")
    if msg_type == "SubscriptionConfirmation":
        ok = sns_verify.confirm_subscription(payload)
        return {"ok": ok, "handled": "subscription_confirmation"}
    if msg_type == "UnsubscribeConfirmation":
        # 우리가 구독을 끊은 것 — 기록만 남긴다(운영자가 의도한 변경일 수 있다).
        logger.warning("SES 웹훅 구독 해지 통지 topic=%s", payload.get("TopicArn"))
        return {"ok": True, "handled": "unsubscribe_confirmation"}
    if msg_type != "Notification":
        logger.info("SES 웹훅: 처리 대상 아님 type=%s", msg_type)
        return {"ok": True, "handled": "ignored"}

    try:
        message = json.loads(payload.get("Message") or "{}")
    except Exception:
        logger.warning("SES 웹훅: Message 파싱 실패")
        return {"ok": True, "handled": "unparsable_message"}

    event = message.get("eventType") or message.get("notificationType")
    if event == "Bounce":
        return {"ok": True, **_handle_bounce(db, message)}
    if event == "Complaint":
        return {"ok": True, **_handle_complaint(db, message)}

    # Delivery·Send·Open 등은 억제 대상이 아니다. 원장은 발송 시점에 이미 남는다.
    logger.info("SES 웹훅: 억제 무관 이벤트 event=%s", event)
    return {"ok": True, "handled": "noop", "event": event}
