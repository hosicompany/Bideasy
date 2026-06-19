from fastapi import APIRouter, Depends, HTTPException
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
from app.core.security import get_current_user, verify_password, get_password_hash, create_token_for_user

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


@router.put("/me/password")
def change_password(
    payload: user_schemas.PasswordChange,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """비밀번호 변경 — 현재 비밀번호 확인 후 새 비밀번호로 교체.

    소셜 전용 계정(비번 없음)은 변경 불가. 새 비번은 8자 이상.
    """
    if not current_user.hashed_password:
        raise HTTPException(
            status_code=400,
            detail="소셜 로그인 계정은 비밀번호가 없어요. 카카오·네이버로 로그인해 주세요.",
        )
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 올바르지 않아요.")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="새 비밀번호는 8자 이상이어야 해요.")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="새 비밀번호가 기존과 동일해요.")

    current_user.hashed_password = get_password_hash(payload.new_password)
    # 토큰 무효화: 비밀번호 변경 시 기존에 발급된 모든 JWT 를 무효화한다
    # (유출 토큰 차단). 현재 클라이언트는 응답의 새 access_token 으로 교체한다.
    current_user.token_version = (current_user.token_version or 0) + 1
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    new_token = create_token_for_user(current_user)
    return {
        "status": "ok",
        "message": "비밀번호가 변경되었어요.",
        "access_token": new_token,
        "token_type": "bearer",
    }


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
