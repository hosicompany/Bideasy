import secrets as _secrets
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.db import models

SECRET_KEY = settings.JWT_SECRET_KEY
ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.JWT_EXPIRE_MINUTES
NOTICE_CHECK_RECEIPT_PURPOSE = "notice_check_activation"
NOTICE_CHECK_RECEIPT_TTL_SECONDS = 120
_NOTICE_CHECK_RECEIPT_MAX_TTL_SECONDS = 300
_RECEIPT_BID_NO_RE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
_RECEIPT_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_token_for_user(user: "models.User") -> str:
    """사용자용 액세스 토큰 — token_version(tv) 클레임 포함.

    tv 는 무효화에 쓰인다(비밀번호 변경/로그아웃 시 User.token_version 증가 →
    옛 tv 를 가진 기존 토큰은 get_current_user 에서 거부됨).
    """
    return create_access_token({"sub": str(user.id), "tv": getattr(user, "token_version", 0) or 0})


class InvalidNoticeCheckReceipt(ValueError):
    """Raised when an activation receipt is forged, expired, or context-mismatched."""


def create_notice_check_receipt(
    *,
    user_id: int,
    bid_no: str,
    expires_seconds: int = NOTICE_CHECK_RECEIPT_TTL_SECONDS,
) -> str:
    """Sign a minimal, short-lived proof that this user received real bid context.

    JWTs are signed, not encrypted. Keep this payload deliberately limited to the
    activation binding and an opaque nonce; never add email, page URL, or referrer.
    One-time consumption is enforced by the growth-event ledger at the POST sink.
    """
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id must be a positive integer")
    if not isinstance(bid_no, str) or not _RECEIPT_BID_NO_RE.fullmatch(bid_no):
        raise ValueError("bid_no must be canonical")
    if not 1 <= expires_seconds <= _NOTICE_CHECK_RECEIPT_MAX_TTL_SECONDS:
        raise ValueError("receipt TTL is outside the allowed range")

    issued_at = datetime.now(timezone.utc)
    payload = {
        "purpose": NOTICE_CHECK_RECEIPT_PURPOSE,
        "user_id": user_id,
        "bid_no": bid_no,
        "nonce": _secrets.token_urlsafe(18),
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=expires_seconds),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_notice_check_receipt(
    receipt: str,
    *,
    expected_user_id: int,
    expected_bid_no: str,
) -> str:
    """Validate a context receipt and return its opaque one-time nonce.

    All failures collapse to one exception type so callers do not reveal whether a
    signed receipt belonged to another user, another bid, or merely expired.
    """
    try:
        payload = jwt.decode(receipt, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        bid_no = payload.get("bid_no")
        nonce = payload.get("nonce")
        issued_at = int(payload.get("iat"))
        expires_at = int(payload.get("exp"))
    except (JWTError, TypeError, ValueError) as exc:
        raise InvalidNoticeCheckReceipt("invalid notice-check receipt") from exc

    now = int(datetime.now(timezone.utc).timestamp())
    valid = (
        payload.get("purpose") == NOTICE_CHECK_RECEIPT_PURPOSE
        and isinstance(user_id, int)
        and not isinstance(user_id, bool)
        and user_id == expected_user_id
        and isinstance(bid_no, str)
        and bid_no == expected_bid_no
        and isinstance(nonce, str)
        and _RECEIPT_NONCE_RE.fullmatch(nonce) is not None
        and issued_at <= now + 30
        and expires_at > issued_at
        and expires_at - issued_at <= _NOTICE_CHECK_RECEIPT_MAX_TTL_SECONDS
    )
    if not valid:
        raise InvalidNoticeCheckReceipt("invalid notice-check receipt")
    return nonce


def create_oauth_state(
    expires_minutes: int = 10,
    attribution: dict[str, str] | None = None,
) -> str:
    """OAuth CSRF 방어용 서명 state.

    서버가 발급했음을 HMAC 서명으로 보증하고 TTL(기본 10분)로 재사용을 제한한다.
    별도 저장소(Redis/세션) 없이 멀티워커에서 검증 가능 — 공격자가 임의 state 를
    위조해 콜백을 위조하는 로그인 CSRF 를 차단한다.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"purpose": "oauth_state", "nonce": _secrets.token_urlsafe(8), "exp": expire}
    # OAuth state는 서명될 뿐 암호화되지 않는다. access token, 이메일, referrer
    # URL 같은 민감값은 허용하지 않고 사전 정규화된 캠페인 좌표만 담는다.
    if attribution:
        allowed = {
            "source": 120,
            "medium": 120,
            "campaign": 160,
            "content": 160,
            "creative_id": 36,
        }
        snapshot = {
            key: value
            for key, limit in allowed.items()
            if isinstance((value := attribution.get(key)), str)
            and value
            and len(value) <= limit
        }
        if snapshot:
            payload["attribution"] = snapshot
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_oauth_state(state: Optional[str]) -> dict | None:
    """유효한 OAuth state payload를 반환하고 위조·만료값은 None으로 닫는다."""
    if not state:
        return None
    try:
        payload = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("purpose") != "oauth_state":
        return None
    return payload


def verify_oauth_state(state: Optional[str]) -> bool:
    """create_oauth_state 가 발급한 유효(미만료) state 인지 검증."""
    return decode_oauth_state(state) is not None


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 정보가 유효하지 않습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            raise credentials_exception
        user_id = int(sub)
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise credentials_exception
    # 토큰 무효화 검사: 토큰의 tv 가 현재 token_version 과 다르면 거부
    # (비밀번호 변경/로그아웃으로 무효화된 토큰. tv 없는 옛 토큰은 0 으로 간주.)
    if payload.get("tv", 0) != (user.token_version or 0):
        raise credentials_exception
    return user


# ── 선택적 인증 ─────────────────────────────────────────────
# 익명 호출도 허용하되, 토큰이 유효하면 사용자 정보를 반환하는 의존성.
# Bearer 토큰을 직접 읽어 oauth2_scheme 의 자동 401 동작을 우회한다.
# (예: /prediction/{bid_no}/recommend-points 의 qualification 검사는
#  로그인 시에만 본인 자격을 검사하고, 익명은 빈 qualification 으로 응답)
_optional_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user_optional(
    token: Optional[str] = Depends(_optional_oauth2),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    """토큰이 있고 유효하면 User, 없거나 유효하지 않으면 None.

    유효하지 않은 토큰을 401 로 거부하지 않고 None 으로 처리하는 이유:
    이 의존성을 쓰는 엔드포인트는 본질적으로 익명 호출도 허용되기 때문.
    엄격한 인증이 필요한 곳은 get_current_user 를 그대로 사용.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            return None
        user_id = int(sub)
    except (JWTError, ValueError):
        return None
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        return None
    if payload.get("tv", 0) != (user.token_version or 0):
        return None
    return user


def require_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    """관리자 권한 검증 — users.is_admin == True 필수.

    Trial·Pro·Pro+ 와 무관하게 is_admin 컬럼만 본다. /admin/* 모든 엔드포인트에
    이 가드를 적용해야 함. 미적용 라우트는 `tests/test_admin_auth.py` 의
    `test_all_admin_routes_have_guard` 가 자동 검출.
    """
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )
    return current_user


def require_tier(minimum_tier: str):
    """
    Dependency that checks if the current user meets the minimum tier.

    체험(Trial) 활성 사용자는 Pro 권한으로 취급됨 (get_effective_tier 가 통합 판정).
    유료 구독 만료 시 자동으로 Free 다운그레이드.

    Usage:
        @router.get("/premium-feature")
        def endpoint(user=Depends(require_tier("pro"))):
            ...
    """
    from app.schemas.subscription import (
        tier_at_least,
        TIER_DISPLAY_NAMES_KO,
        get_effective_tier,
    )

    def _check(current_user: models.User = Depends(get_current_user)):
        effective_tier = get_effective_tier(current_user)

        if not tier_at_least(effective_tier, minimum_tier):
            tier_name = TIER_DISPLAY_NAMES_KO.get(minimum_tier, minimum_tier)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"이 기능은 {tier_name} 이상 구독이 필요해요.",
            )
        return current_user

    return _check
