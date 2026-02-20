from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import httpx

from app.db.session import get_db
from app.db import models
from app.schemas import user as user_schemas
from app.schemas.point import SIGNUP_BONUS
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

KAKAO_USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"
NAVER_USER_INFO_URL = "https://openapi.naver.com/v1/nid/me"

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
    if not user or not user.hashed_password or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.id})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/social")
async def social_login(
    payload: user_schemas.SocialLoginRequest,
    db: Session = Depends(get_db),
):
    """카카오/네이버 소셜 로그인"""
    social_id = None
    email = None
    profile_image = None

    async with httpx.AsyncClient() as client:
        if payload.provider == "kakao":
            resp = await client.get(
                KAKAO_USER_INFO_URL,
                headers={"Authorization": f"Bearer {payload.access_token}"},
            )
            if resp.status_code != 200:
                logger.warning(f"Kakao token verification failed: {resp.status_code}")
                raise HTTPException(status_code=401, detail="카카오 토큰 검증에 실패했어요")
            data = resp.json()
            social_id = str(data["id"])
            kakao_account = data.get("kakao_account", {})
            email = kakao_account.get("email")
            profile_image = kakao_account.get("profile", {}).get("thumbnail_image_url")

        elif payload.provider == "naver":
            resp = await client.get(
                NAVER_USER_INFO_URL,
                headers={"Authorization": f"Bearer {payload.access_token}"},
            )
            if resp.status_code != 200:
                logger.warning(f"Naver token verification failed: {resp.status_code}")
                raise HTTPException(status_code=401, detail="네이버 토큰 검증에 실패했어요")
            result = resp.json()
            if result.get("resultcode") != "00":
                raise HTTPException(status_code=401, detail="네이버 토큰 검증에 실패했어요")
            data = result["response"]
            social_id = data["id"]
            email = data.get("email")
            profile_image = data.get("profile_image")

        else:
            raise HTTPException(status_code=400, detail="지원하지 않는 소셜 로그인이에요")

    # Find by social identity
    user = db.query(models.User).filter(
        models.User.social_provider == payload.provider,
        models.User.social_id == social_id,
    ).first()

    # Or link to existing email account
    if not user and email:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user:
            user.social_provider = payload.provider
            user.social_id = social_id
            if profile_image:
                user.profile_image_url = profile_image

    # Create new user
    if not user:
        user = models.User(
            email=email,
            hashed_password=None,
            social_provider=payload.provider,
            social_id=social_id,
            profile_image_url=profile_image,
            points=SIGNUP_BONUS,
        )
        db.add(user)
        db.flush()
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

    access_token = create_access_token(data={"sub": user.id})
    logger.info(f"Social login: provider={payload.provider}, user_id={user.id}")
    return {"access_token": access_token, "token_type": "bearer"}
