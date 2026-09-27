from slowapi import Limiter
from fastapi import Request

from app.core.client_meta import client_ip
from app.core.config import settings


def _key_func(request: Request) -> str:
    """Extract user_id from JWT if available, otherwise use IP."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            from jose import jwt
            token = auth.split(" ", 1)[1]
            payload = jwt.decode(
                token, settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            user_id = payload.get("sub")
            if user_id:
                return f"user:{user_id}"
        except Exception:
            pass
    # IP 판정은 client_meta 한 곳 — XFF 첫 요소(위조 가능)가 아니라 nginx 가 붙인 마지막 홉.
    return client_ip(request)


def get_user_tier(request: Request) -> str:
    """Extract user tier from JWT for dynamic rate limiting.

    Decodes the JWT to get user_id, then queries the DB for tier.
    Falls back to 'free' on any error.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            from jose import jwt
            token = auth.split(" ", 1)[1]
            payload = jwt.decode(
                token, settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            user_id = payload.get("sub")
            if user_id:
                from app.db.session import SessionLocal
                from app.db import models
                db = SessionLocal()
                try:
                    user = db.query(models.User).filter(
                        models.User.id == int(user_id)
                    ).first()
                    return getattr(user, "tier", "free") or "free"
                finally:
                    db.close()
        except Exception:
            pass
    return "free"


limiter = Limiter(key_func=_key_func)
