"""Amazon SNS 메시지 진위 검증.

**이 검증이 없으면 웹훅은 공격 도구가 된다.** 엔드포인트는 인증 없이 열려 있어야 하고
(SNS 는 우리 토큰을 모른다), 하는 일은 "이 주소로 다시는 보내지 마라"이다. 검증을 빼면
누구나 가짜 반송 이벤트를 던져 **임의의 고객 주소를 발송 금지로 만들 수 있다** — 조용하고
되돌리기 어려운 서비스 거부다.

그래서 두 겹으로 막는다:
  1. **서명 검증**: SNS 가 공개키로 서명한 값을 검증(SHA1WithRSA=v1, SHA256WithRSA=v2).
     서명 대상 문자열은 메시지 타입별로 필드 순서가 고정돼 있다(AWS 규격).
  2. **인증서 출처 고정**: `SigningCertURL` 은 반드시 `sns.<region>.amazonaws.com` 호스트여야
     한다. 이걸 안 막으면 공격자가 자기 서버의 인증서를 가리켜 서명을 자작할 수 있다.

TopicArn 화이트리스트(`SNS_TOPIC_ARN`)까지 맞추면, 유효한 다른 AWS 계정의 토픽이
우리 엔드포인트를 건드리는 것도 막힌다.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.x509 import load_pem_x509_certificate

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# SigningCertURL 허용 호스트 — SNS 공식 엔드포인트만.
_CERT_HOST_RE = re.compile(r"^sns\.[a-z0-9-]+\.amazonaws\.com$")
# SubscribeURL 도 동일 출처여야 한다(확인 요청을 아무 데나 GET 하지 않는다).
_SUBSCRIBE_HOST_RE = _CERT_HOST_RE

# 서명 대상 필드 순서 (AWS 규격 — 순서를 바꾸면 검증이 깨진다)
_SIGN_FIELDS = {
    "Notification": ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"],
    "SubscriptionConfirmation": [
        "Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type",
    ],
    "UnsubscribeConfirmation": [
        "Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type",
    ],
}

_cert_cache: dict[str, bytes] = {}


class SnsVerificationError(ValueError):
    """서명·출처·토픽 검증 실패. 호출부는 403 으로 응답한다."""


def _check_host(url: Optional[str], pattern: re.Pattern, label: str) -> str:
    if not url:
        raise SnsVerificationError(f"{label} 없음")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not pattern.match(parsed.netloc):
        raise SnsVerificationError(f"{label} 출처가 SNS 가 아님: {parsed.netloc}")
    return url


def _fetch_certificate(url: str) -> bytes:
    if url in _cert_cache:
        return _cert_cache[url]
    resp = httpx.get(url, timeout=5.0)
    resp.raise_for_status()
    _cert_cache[url] = resp.content
    return resp.content


def _string_to_sign(payload: dict) -> bytes:
    msg_type = payload.get("Type")
    fields = _SIGN_FIELDS.get(msg_type)
    if not fields:
        raise SnsVerificationError(f"알 수 없는 메시지 타입: {msg_type}")
    parts = []
    for field in fields:
        value = payload.get(field)
        if value is None:
            continue  # Subject 처럼 없을 수 있는 필드는 통째로 제외(AWS 규격)
        parts.append(field)
        parts.append(str(value))
    return ("\n".join(parts) + "\n").encode("utf-8")


def verify(payload: dict) -> None:
    """검증 실패 시 SnsVerificationError. 성공하면 조용히 반환."""
    expected_topic = (settings.SES_SNS_TOPIC_ARN or "").strip()
    if expected_topic and payload.get("TopicArn") != expected_topic:
        raise SnsVerificationError("허용되지 않은 TopicArn")

    cert_url = _check_host(payload.get("SigningCertURL"), _CERT_HOST_RE, "SigningCertURL")

    signature_b64 = payload.get("Signature")
    if not signature_b64:
        raise SnsVerificationError("Signature 없음")
    import base64

    try:
        signature = base64.b64decode(signature_b64)
    except Exception as exc:  # noqa: BLE001
        raise SnsVerificationError("Signature 디코딩 실패") from exc

    try:
        cert_pem = _fetch_certificate(cert_url)
    except Exception as exc:  # noqa: BLE001
        raise SnsVerificationError(f"인증서 조회 실패: {exc}") from exc

    try:
        cert = load_pem_x509_certificate(cert_pem)
        public_key = cert.public_key()
    except Exception:  # noqa: BLE001 — 드물게 공개키 PEM 이 오는 경우 대비
        try:
            public_key = load_pem_public_key(cert_pem)
        except Exception as exc:  # noqa: BLE001
            raise SnsVerificationError("인증서 파싱 실패") from exc

    version = str(payload.get("SignatureVersion", "1"))
    if version == "2":
        from cryptography.hazmat.primitives.hashes import SHA256 as _H
    elif version == "1":
        from cryptography.hazmat.primitives.hashes import SHA1 as _H
    else:
        raise SnsVerificationError(f"지원하지 않는 SignatureVersion: {version}")

    try:
        public_key.verify(signature, _string_to_sign(payload), padding.PKCS1v15(), _H())
    except SnsVerificationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SnsVerificationError("서명 불일치") from exc


def confirm_subscription(payload: dict) -> bool:
    """SubscriptionConfirmation 자동 승인 — SubscribeURL 을 GET 하면 구독이 활성화된다.

    출처를 SNS 호스트로 고정한 뒤에만 호출한다(임의 URL 을 서버가 긁게 두지 않는다).
    실패해도 예외를 올리지 않고 False 를 반환한다 — 여기서 5xx 를 내면 SNS 가 같은
    메시지를 무한 재시도한다.
    """
    try:
        url = _check_host(payload.get("SubscribeURL"), _SUBSCRIBE_HOST_RE, "SubscribeURL")
    except SnsVerificationError as exc:
        logger.warning("SNS 구독 확인 거부(출처 불일치): %s", exc)
        return False
    try:
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
        logger.info("SNS 구독 확인 완료 topic=%s", payload.get("TopicArn"))
        return True
    except Exception as exc:  # noqa: BLE001 — 실패해도 SNS 가 재시도한다
        logger.warning("SNS 구독 확인 실패: %s", exc)
        return False
