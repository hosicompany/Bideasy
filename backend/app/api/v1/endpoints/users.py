from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Any

from app.db import models
from app.schemas import user as user_schemas
from app.schemas.subscription import (
    TrialStatus,
    is_trial_active,
    trial_days_remaining,
    has_used_trial,
)
from app.db.session import get_db
from app.core.security import get_current_user

router = APIRouter()

@router.get("/me", response_model=user_schemas.UserResponse)
def get_user_me(current_user: models.User = Depends(get_current_user)) -> Any:
    """현재 로그인한 사용자 프로필 조회"""
    return current_user

@router.put("/me", response_model=user_schemas.UserResponse)
def update_user_me(
    user_in: user_schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Any:
    """현재 로그인한 사용자 프로필 수정"""
    update_data = user_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(current_user, field, value)

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/me/trial", response_model=TrialStatus)
def get_trial_status(
    current_user: models.User = Depends(get_current_user),
) -> TrialStatus:
    """현재 사용자의 체험(Trial) 상태 — 익스텐션 헤더·마이페이지용 경량 엔드포인트.

    is_active: 지금 체험이 활성 (Pro 권한 부여 중)
    days_remaining: 만료까지 남은 일수 (0 = 만료됨 또는 없음)
    expires_at: 만료 시각 (없으면 null)
    has_used: 이미 체험을 시작한 이력이 있는지 (재체험 방지 플래그)
    """
    return TrialStatus(
        is_active=is_trial_active(current_user),
        days_remaining=trial_days_remaining(current_user),
        expires_at=current_user.trial_expires_at,
        has_used=has_used_trial(current_user),
    )
