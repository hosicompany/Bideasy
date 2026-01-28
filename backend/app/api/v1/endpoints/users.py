from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any

from app.db import models
from app.schemas import user as user_schemas
from app.db.session import get_db

router = APIRouter()

@router.get("/me", response_model=user_schemas.UserResponse)
def get_user_me(db: Session = Depends(get_db)) -> Any:
    """
    Get current user profile (Mock Auth: ID 1).
    Creates default user if not exists.
    """
    user_id = 1
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        # Create default user
        user = models.User(
            id=user_id,
            email="test@example.com",
            hashed_password="mock_password",
            company_name="내 건설사",
            points=100
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

@router.put("/me", response_model=user_schemas.UserResponse)
def update_user_me(
    user_in: user_schemas.UserUpdate,
    db: Session = Depends(get_db)
) -> Any:
    """
    Update current user profile.
    """
    user_id = 1
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
         raise HTTPException(status_code=404, detail="User not found")
        
    update_data = user_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
        
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
