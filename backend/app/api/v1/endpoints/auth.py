from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db import models
from app.schemas import user as user_schemas
from app.schemas.point import SIGNUP_BONUS
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user,
)

router = APIRouter()


@router.post("/register", response_model=user_schemas.UserResponse)
def register(user_in: user_schemas.UserCreate, db: Session = Depends(get_db)):
    """회원가입"""
    existing = db.query(models.User).filter(models.User.email == user_in.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 등록된 이메일입니다.",
        )

    user = models.User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        company_name=user_in.company_name,
        ceo_name=user_in.ceo_name,
        licenses=user_in.licenses,
        location=user_in.location,
        capacity_cost=user_in.capacity_cost or 0,
        performance_record=user_in.performance_record or 0,
        points=SIGNUP_BONUS,
    )
    db.add(user)
    db.flush()  # user.id 확보

    # 가입 보너스 거래 기록
    tx = models.PointTransaction(
        user_id=user.id,
        amount=SIGNUP_BONUS,
        balance_after=SIGNUP_BONUS,
        tx_type="SIGNUP_BONUS",
        description=f"신규 가입 보너스 {SIGNUP_BONUS:,}원",
    )
    db.add(tx)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """로그인 (JWT 토큰 발급)"""
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.id})
    return {"access_token": access_token, "token_type": "bearer"}
