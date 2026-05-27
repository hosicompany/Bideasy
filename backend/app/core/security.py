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
    return db.query(models.User).filter(models.User.id == user_id).first()


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
