from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any

from app.db import models
from app.schemas import user as user_schemas
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
