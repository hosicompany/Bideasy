"""이메일 전송 어댑터 (AWS SES) — 채널 구현만 담당.

책임 경계가 중요하다:
  - **이 모듈**: MIME 조립 + SES 호출 + 실패 변환. 수신동의를 판단하지 않는다.
  - `services/nurture.py`: 보낼 자격이 있는지(동의·철회·중복) 판정하고 원장에 남긴다.
동의 판정을 어댑터에 두면, 나중에 알림톡 어댑터를 붙일 때 같은 규칙을 또 구현하게 되고
한쪽만 고쳐져 사고가 난다. 그래서 게이트는 nurture 한 곳에만 있다.

**기본값은 전송 OFF**(`OUTBOUND_EMAIL_ENABLED=False`) — SES 프로덕션 승인·DKIM 인증 전에
켜지면 샌드박스 거절이나 미인증 도메인 발송으로 평판이 깎인다. OFF 면 실제 전송 없이
`dry_run` 을 반환하고 내용은 로그로만 남는다(파이프라인 전체는 그대로 돈다).
"""
from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MailerError(RuntimeError):
    """전송 실패(자격증명·검증·스로틀 등). 호출부가 원장에 failed 로 남긴다."""


@dataclass
class SendResult:
    status: str                      # sent | dry_run
    provider: str                    # ses | none
    message_id: Optional[str] = None


def _from_header() -> str:
    name = (settings.SES_FROM_NAME or "").strip()
    addr = settings.SES_FROM_EMAIL
    return f"{name} <{addr}>" if name else addr


def build_message(
    *,
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
    headers: Optional[dict] = None,
) -> EmailMessage:
    """MIME 조립. 원문(raw) 전송을 쓰는 이유는 `List-Unsubscribe` 같은 헤더 때문이다.

    SES 의 SendEmail API 는 임의 헤더를 넣을 수 없어 원클릭 수신거부(RFC 8058)를
    구현할 수 없다. 수신거부 편의는 법적 요구(정보통신망법)이자 스팸 판정 방어책이다.
    """
    msg = EmailMessage()
    msg["From"] = _from_header()
    msg["To"] = to
    msg["Subject"] = subject
    if settings.SES_REPLY_TO:
        msg["Reply-To"] = settings.SES_REPLY_TO
    for key, value in (headers or {}).items():
        if value:
            msg[key] = value
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


# SES 호출 상한 — 요청 스레드를 오래 붙잡지 않기 위한 값이다. 합계 최악 ~7초.
_SES_CONNECT_TIMEOUT = 3
_SES_READ_TIMEOUT = 4
_SES_MAX_ATTEMPTS = 1          # 재시도는 하지 않는다. 실패한 메일은 원장에 남고 재시도 가능.


def _botocore_config():
    from botocore.config import Config

    return Config(
        connect_timeout=_SES_CONNECT_TIMEOUT,
        read_timeout=_SES_READ_TIMEOUT,
        retries={"max_attempts": _SES_MAX_ATTEMPTS, "mode": "standard"},
    )


def send(
    *,
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
    headers: Optional[dict] = None,
) -> SendResult:
    """이메일 1통 전송. 킬스위치가 꺼져 있으면 dry_run 으로 즉시 반환."""
    try:
        msg = build_message(to=to, subject=subject, text=text, html=html, headers=headers)
    except (ValueError, TypeError) as exc:
        # 제목·헤더에 개행이 섞이면 email 패키지가 ValueError 를 던진다(헤더 인젝션 방어).
        # 이걸 그대로 흘리면 호출부의 `except MailerError` 를 지나쳐 배치 전체를 죽이므로
        # 여기서 도메인 예외로 변환한다 — 조립 실패도 '이 한 통의 실패'여야 한다.
        raise MailerError(f"메시지 조립 실패: {exc}") from exc

    if not settings.OUTBOUND_EMAIL_ENABLED:
        logger.info("[dry-run] email to=%s subject=%s", to, subject)
        return SendResult(status="dry_run", provider="none")

    # 아래 SES 호출은 **요청 스레드에서 동기로** 일어날 수 있다(가입·리드 캡처).
    # botocore 기본값은 connect/read 각 60초 + 재시도라, SES 가 한 번 느려지면 그 요청이
    # nginx 타임아웃에 걸려 죽는다 — 사용자에겐 '가입 실패'인데 계정은 이미 만들어진
    # 사각지대가 생긴다. 메일 한 통은 늦게 가도 되지만 가입은 늦으면 안 된다.

    try:
        import boto3  # 지연 import — 발송을 켜지 않은 환경에 의존성을 강요하지 않는다
    except ImportError as exc:
        raise MailerError("boto3 미설치 — SES 전송 불가") from exc

    client_kwargs = {"region_name": settings.AWS_REGION, "config": _botocore_config()}
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

    kwargs = {
        "Source": settings.SES_FROM_EMAIL,
        "Destinations": [to],
        "RawMessage": {"Data": msg.as_bytes()},
    }
    if settings.SES_CONFIGURATION_SET:
        kwargs["ConfigurationSetName"] = settings.SES_CONFIGURATION_SET

    try:
        client = boto3.client("ses", **client_kwargs)
        resp = client.send_raw_email(**kwargs)
    except Exception as exc:  # noqa: BLE001 — botocore 예외 계층을 여기서 노출하지 않는다
        raise MailerError(str(exc)[:280]) from exc

    return SendResult(status="sent", provider="ses", message_id=resp.get("MessageId"))
