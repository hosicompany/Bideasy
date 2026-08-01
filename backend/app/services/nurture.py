"""아웃바운드 발송 오케스트레이션 — 게이트·멱등·원장.

발송 경로는 여기 하나뿐이다. 태스크·엔드포인트가 `mailer.send()` 를 직접 부르면
동의 게이트와 원장 기록을 우회하게 되므로, 발송이 필요한 코드는 반드시 이 모듈의
`send_marketing` / `send_transactional` 을 쓴다.

두 함수를 나눈 이유는 법이 둘을 다르게 취급하기 때문이다:
  - **marketing**: 광고성 정보. 사전 동의 필수(정보통신망법 §50), 제목 "(광고)" 표기,
    수신거부 수단 제공. 동의가 없으면 **보내지 않고 skipped 로 남긴다.**
  - **transactional**: 체험 만료·결제·영수증 같은 거래 관련 고지. 광고가 아니므로
    동의와 무관하게 발송하되, 마케팅 문구를 끼워 넣지 않는다(끼우는 순간 광고가 된다).

멱등: `dedupe_key` 를 주면 전송 **시도 전에** 원장에 선점(claim) 행을 넣는다. 동시에
두 워커가 같은 키를 들고 와도 유니크 제약이 한쪽을 떨어뜨린다. 전송이 실패하면 키를
비워 재시도 여지를 남긴다.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.signed_token import make_token
from app.db import models
from app.services import consent as consent_service
from app.services import email_templates, mailer, suppression

logger = get_logger(__name__)

# 수신거부 토큰의 용도 라벨 — 다른 용도로 재사용 불가(core/signed_token.py 참조)
UNSUB_PURPOSE = "unsub"


def unsubscribe_token(subject_type: str, subject_id: int) -> str:
    return make_token(UNSUB_PURPOSE, subject_type, subject_id)


def unsubscribe_url(subject_type: str, subject_id: int) -> str:
    """사람이 눌러서 확인·해지하는 웹 페이지."""
    token = unsubscribe_token(subject_type, subject_id)
    return f"{settings.PUBLIC_WEB_URL}/unsubscribe?t={token}"


def one_click_unsubscribe_url(subject_type: str, subject_id: int) -> str:
    """메일 클라이언트가 자동으로 호출하는 원클릭 해지 엔드포인트(RFC 8058)."""
    token = unsubscribe_token(subject_type, subject_id)
    return f"{settings.PUBLIC_API_URL}/api/v1/unsubscribe?token={token}"


def _log(
    db: Session,
    *,
    subject_type: str,
    subject_id: Optional[int],
    email: Optional[str],
    template: str,
    category: str,
    status: str,
    reason: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    subject: Optional[str] = None,
) -> models.OutboundMessage:
    row = models.OutboundMessage(
        subject_type=subject_type,
        subject_id=subject_id,
        email=email,
        channel="email",
        template=template,
        category=category,
        subject=subject,
        status=status,
        reason=reason,
        dedupe_key=dedupe_key,
    )
    db.add(row)
    db.commit()
    return row


def _send(
    db: Session,
    subject_obj,
    *,
    subject_type: str,
    template: str,
    ctx: Optional[dict] = None,
    dedupe_key: Optional[str] = None,
) -> models.OutboundMessage:
    category = email_templates.category_of(template)
    subject_id = getattr(subject_obj, "id", None)
    email = (getattr(subject_obj, "email", None) or "").strip() or None

    def skipped(reason: str) -> models.OutboundMessage:
        # skipped 행에는 dedupe_key 를 남기지 않는다 — 나중에 조건이 풀렸을 때
        # (예: 동의를 새로 받음) 유니크 제약이 재발송을 영구히 막으면 안 된다.
        logger.info("nurture skip template=%s subject=%s:%s reason=%s",
                    template, subject_type, subject_id, reason)
        return _log(db, subject_type=subject_type, subject_id=subject_id, email=email,
                    template=template, category=category, status="skipped", reason=reason)

    if not email:
        return skipped("no_email")

    # 억제 목록은 **광고·거래를 가리지 않고** 먼저 걸린다. 하드 반송·불만 주소에 계속
    # 보내면 반송률·불만율이 올라 계정 발송이 정지되고, 그러면 거래 메일까지 막힌다.
    if suppression.is_suppressed(db, email):
        return skipped("suppressed")

    # 광고성 정보는 동의 게이트 통과가 유일한 발송 조건이다.
    if category == "marketing" and not consent_service.can_send_marketing(subject_obj):
        return skipped("no_consent")

    # ── 멱등 선점 ──
    row = models.OutboundMessage(
        subject_type=subject_type, subject_id=subject_id, email=email,
        channel="email", template=template, category=category,
        status="sending", dedupe_key=dedupe_key,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return skipped("duplicate")

    # 선점 커밋 이후의 모든 단계를 한 번에 감싼다. 렌더·헤더 조립도 실패할 수 있는데
    # (템플릿 ctx 결함, 제목에 섞인 제어문자 등) 그 예외가 빠져나가면 원장에 status="sending"
    # + dedupe_key 를 점유한 유령행이 영구히 남아, 원인을 고쳐도 그 대상에게 **재발송이
    # 불가능**해진다. 실패는 언제나 "키를 놓은 failed" 로 수렴해야 한다.
    try:
        unsub = unsubscribe_url(subject_type, subject_id) if subject_id else None
        rendered = email_templates.render(template, ctx, unsubscribe_url=unsub)

        headers = {}
        if category == "marketing" and subject_id:
            # 원클릭 수신거부 — 스팸 신고 대신 해지를 누르게 만드는 가장 효과적인 장치이자
            # 주요 메일 사업자의 대량 발신 요구사항(RFC 8058).
            headers["List-Unsubscribe"] = (
                f"<{one_click_unsubscribe_url(subject_type, subject_id)}>, <mailto:{email_templates.SENDER_CONTACT}>"
            )
            headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        row.subject = rendered.subject
        result = mailer.send(
            to=email, subject=rendered.subject, text=rendered.text,
            html=rendered.html, headers=headers,
        )
        row.status = result.status              # sent | dry_run
        row.provider = result.provider
        row.provider_message_id = result.message_id
    except Exception as exc:  # noqa: BLE001 — 발송 실패가 호출부를 죽이지 않는다
        row.status = "failed"
        row.error = str(exc)[:300]
        row.dedupe_key = None                   # 재시도 가능하게 키 해제
        logger.warning("nurture send failed template=%s to=%s: %s", template, email, exc)
    db.commit()
    return row


def send_marketing(
    db: Session,
    subject_obj,
    *,
    subject_type: str,
    template: str,
    ctx: Optional[dict] = None,
    dedupe_key: Optional[str] = None,
) -> models.OutboundMessage:
    """광고성 메일 — 동의 게이트를 통과한 대상에게만 실제로 나간다."""
    if email_templates.category_of(template) != "marketing":
        raise ValueError(f"'{template}' 은 광고 템플릿이 아니다")
    return _send(db, subject_obj, subject_type=subject_type, template=template,
                 ctx=ctx, dedupe_key=dedupe_key)


def send_transactional(
    db: Session,
    subject_obj,
    *,
    subject_type: str,
    template: str,
    ctx: Optional[dict] = None,
    dedupe_key: Optional[str] = None,
) -> models.OutboundMessage:
    """거래 관련 고지 — 수신동의와 무관. 광고 문구를 섞지 않는다."""
    if email_templates.category_of(template) != "transactional":
        raise ValueError(f"'{template}' 은 거래 템플릿이 아니다")
    return _send(db, subject_obj, subject_type=subject_type, template=template,
                 ctx=ctx, dedupe_key=dedupe_key)
