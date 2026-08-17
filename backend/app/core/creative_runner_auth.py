"""Rotating bearer-token authentication for the local creative runner."""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings


_bearer = HTTPBearer(auto_error=False)


def require_creative_runner(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Accept the current token and, during rotation, the previous token.

    A missing server-side token closes the endpoint instead of silently enabling a
    development bypass. Token values are compared in constant time and never logged.
    """
    accepted = [
        token
        for token in (
            settings.CREATIVE_RUNNER_TOKEN_CURRENT,
            settings.CREATIVE_RUNNER_TOKEN_PREVIOUS,
        )
        if token
    ]
    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="creative runner 인증이 설정되지 않았어요",
        )
    supplied = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
    if not supplied or not any(secrets.compare_digest(supplied, token) for token in accepted):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="creative runner 인증에 실패했어요",
            headers={"WWW-Authenticate": "Bearer"},
        )
