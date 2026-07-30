"""용도 한정 서명 토큰 — 로그인 없이 안전하게 1가지 행위만 허용.

수신거부 링크가 첫 사용처다. 메일을 받은 사람은 로그인 상태가 아니고, 로그인을
요구하면 "쉬운 수신거부"(정보통신망법 시행령 §61의3 취지)를 해치므로 링크 자체가
권한이어야 한다. 그래서 다음을 지킨다:

- **JWT 를 쓰지 않는다.** 세션 토큰과 같은 형식이면 오용·혼동 위험이 있다. 여기서
  만드는 토큰은 `purpose` 로 용도가 못 박혀 있어 다른 엔드포인트에 재사용될 수 없다.
- **만료를 두지 않는다(기본).** 수신거부는 "언제든" 가능해야 한다. 6개월 전 메일의
  링크가 죽어 있으면 사용자는 거부할 방법을 잃는다.
- **정보를 담지 않는다.** payload 는 주체 종류·id 뿐이다. 노출돼도 상태 변경(수신거부)
  외에는 아무것도 못 한다.
- 서명 키는 `JWT_SECRET_KEY` 를 재사용하되 purpose 를 HMAC 입력에 섞어 도메인 분리한다.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Optional, Tuple

from app.core.config import settings

_SEP = "."


class InvalidSignedToken(ValueError):
    """서명 불일치·형식 오류·용도 불일치 — 모두 같은 실패로 다룬다(정보 노출 최소화)."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(purpose: str, payload: str) -> str:
    key = (settings.JWT_SECRET_KEY or "").encode()
    msg = f"{purpose}{_SEP}{payload}".encode()
    return _b64e(hmac.new(key, msg, hashlib.sha256).digest())


def make_token(purpose: str, subject_type: str, subject_id: int) -> str:
    """`purpose` 전용 토큰 발급. 예: make_token("unsub", "lead", 42)."""
    payload = _b64e(f"{subject_type}:{int(subject_id)}".encode())
    return f"{payload}{_SEP}{_sign(purpose, payload)}"


def parse_token(purpose: str, token: Optional[str]) -> Tuple[str, int]:
    """토큰 검증 후 (subject_type, subject_id) 반환. 실패 시 InvalidSignedToken."""
    if not token or _SEP not in token:
        raise InvalidSignedToken("malformed")
    payload, _, sig = token.rpartition(_SEP)
    # 타이밍 공격 방지를 위해 상수시간 비교
    if not hmac.compare_digest(sig, _sign(purpose, payload)):
        raise InvalidSignedToken("bad signature")
    try:
        subject_type, _, raw_id = _b64d(payload).decode().partition(":")
        return subject_type, int(raw_id)
    except Exception as exc:  # noqa: BLE001 — 형식 오류는 전부 동일 실패로 수렴
        raise InvalidSignedToken("bad payload") from exc
