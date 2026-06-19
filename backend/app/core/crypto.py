"""민감 필드 at-rest 암호화 (빌링키 등).

설계 원칙(라이브 결제 시스템 안전성):
- `BILLING_ENC_KEY` 미설정 시: 암호화 비활성 → 평문 저장(기존 동작 유지, 무중단).
- `BILLING_ENC_KEY` 설정 시: 신규 저장값은 Fernet 으로 암호화. 읽을 때는
  복호화하되, 복호화 실패(레거시 평문)면 원본을 그대로 반환 → 점진적 마이그레이션.

키 생성: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
→ 출력값을 `.env.production` 의 `BILLING_ENC_KEY` 에 설정.
※ 이 키를 분실하면 암호화된 빌링키를 복구할 수 없으니 안전 보관 필수.
"""
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_PREFIX = "enc::"  # 암호화된 값 식별 접두사 (평문과 구분)


@lru_cache(maxsize=1)
def _fernet() -> Optional[Fernet]:
    key = (settings.BILLING_ENC_KEY or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception as e:  # 잘못된 키 형식
        logger.error(f"BILLING_ENC_KEY 형식 오류 — 암호화 비활성화: {e}")
        return None


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    """민감값 암호화. 키 미설정 시 평문 그대로 반환."""
    if value is None:
        return None
    f = _fernet()
    if f is None:
        return value
    return _PREFIX + f.encrypt(value.encode()).decode()


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    """저장값 복호화. 평문(레거시)·키 미설정이면 원본 반환."""
    if value is None:
        return None
    if not value.startswith(_PREFIX):
        return value  # 레거시 평문 또는 암호화 비활성 시 저장된 값
    f = _fernet()
    if f is None:
        # 암호화된 값인데 키가 없으면 복호화 불가 → 원본 반환(경고)
        logger.error("암호화된 값이지만 BILLING_ENC_KEY 가 없어 복호화 불가")
        return value
    try:
        return f.decrypt(value[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        logger.error("빌링키 복호화 실패(InvalidToken) — 키 불일치 가능")
        return value
