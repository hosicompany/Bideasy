from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import httpx
import secrets as stdlib_secrets

from app.db.session import get_db
from app.db import models
from app.schemas import user as user_schemas
from app.schemas.point import SIGNUP_BONUS
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
)
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

KAKAO_USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"
NAVER_USER_INFO_URL = "https://openapi.naver.com/v1/nid/me"

router = APIRouter()


def _find_or_create_social_user(
    db: Session,
    provider: str,
    social_id: str,
    email: str | None,
    profile_image: str | None,
) -> models.User:
    """Find existing user by social identity, email, or create new one."""
    user = db.query(models.User).filter(
        models.User.social_provider == provider,
        models.User.social_id == social_id,
    ).first()

    if not user and email:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user:
            user.social_provider = provider
            user.social_id = social_id
            if profile_image:
                user.profile_image_url = profile_image

    if not user:
        user = models.User(
            email=email,
            hashed_password=None,
            social_provider=provider,
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
    return user


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

    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/social")
async def social_login(
    payload: user_schemas.SocialLoginRequest,
    db: Session = Depends(get_db),
):
    """카카오/네이버 소셜 로그인 (모바일 SDK용 - access_token 직접 전달)"""
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

    user = _find_or_create_social_user(
        db, provider=payload.provider, social_id=social_id,
        email=email, profile_image=profile_image,
    )

    access_token = create_access_token(data={"sub": str(user.id)})
    logger.info(f"Social login: provider={payload.provider}, user_id={user.id}")
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/social-urls")
def get_social_login_urls():
    """OAuth 인가 URL 반환 (프론트엔드에서 호출)"""
    naver_state = stdlib_secrets.token_urlsafe(16)
    base = f"{settings.BACKEND_URL}{settings.API_V1_STR}"
    kakao_cb = f"{base}/auth/callback/kakao"
    naver_cb = f"{base}/auth/callback/naver"

    return {
        "kakao": (
            f"https://kauth.kakao.com/oauth/authorize"
            f"?client_id={settings.KAKAO_REST_API_KEY}"
            f"&redirect_uri={kakao_cb}"
            f"&response_type=code"
        ),
        "naver": (
            f"https://nid.naver.com/oauth2.0/authorize"
            f"?client_id={settings.NAVER_CLIENT_ID}"
            f"&redirect_uri={naver_cb}"
            f"&response_type=code"
            f"&state={naver_state}"
        ),
    }


@router.get("/callback/kakao")
async def kakao_callback(code: str, db: Session = Depends(get_db)):
    """카카오 OAuth 콜백 - 인가 코드 → JWT → 프론트엔드 리다이렉트"""
    callback_url = f"{settings.BACKEND_URL}{settings.API_V1_STR}/auth/callback/kakao"

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://kauth.kakao.com/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": settings.KAKAO_REST_API_KEY,
                "client_secret": settings.KAKAO_CLIENT_SECRET,
                "redirect_uri": callback_url,
                "code": code,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            logger.warning(f"Kakao token exchange failed: {token_resp.text}")
            return RedirectResponse(f"{settings.FRONTEND_URL}/?error=kakao_token_failed")

        access_token = token_resp.json()["access_token"]

        user_resp = await client.get(
            KAKAO_USER_INFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            return RedirectResponse(f"{settings.FRONTEND_URL}/?error=kakao_userinfo_failed")
        data = user_resp.json()

    social_id = str(data["id"])
    kakao_account = data.get("kakao_account", {})
    email = kakao_account.get("email")
    profile_image = kakao_account.get("profile", {}).get("thumbnail_image_url")

    user = _find_or_create_social_user(
        db, provider="kakao", social_id=social_id,
        email=email, profile_image=profile_image,
    )

    jwt_token = create_access_token(data={"sub": str(user.id)})
    logger.info(f"Kakao OAuth callback: user_id={user.id}")
    return RedirectResponse(f"{settings.FRONTEND_URL}/?token={jwt_token}")


@router.get("/callback/naver")
async def naver_callback(code: str, state: str, db: Session = Depends(get_db)):
    """네이버 OAuth 콜백 - 인가 코드 → JWT → 프론트엔드 리다이렉트"""
    callback_url = f"{settings.BACKEND_URL}{settings.API_V1_STR}/auth/callback/naver"

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://nid.naver.com/oauth2.0/token",
            data={
                "grant_type": "authorization_code",
                "client_id": settings.NAVER_CLIENT_ID,
                "client_secret": settings.NAVER_CLIENT_SECRET,
                "redirect_uri": callback_url,
                "code": code,
                "state": state,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            logger.warning(f"Naver token exchange failed: {token_resp.text}")
            return RedirectResponse(f"{settings.FRONTEND_URL}/?error=naver_token_failed")

        access_token = token_resp.json()["access_token"]

        user_resp = await client.get(
            NAVER_USER_INFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            return RedirectResponse(f"{settings.FRONTEND_URL}/?error=naver_userinfo_failed")
        result = user_resp.json()
        if result.get("resultcode") != "00":
            return RedirectResponse(f"{settings.FRONTEND_URL}/?error=naver_userinfo_failed")
        naver_data = result["response"]

    social_id = naver_data["id"]
    email = naver_data.get("email")
    profile_image = naver_data.get("profile_image")

    user = _find_or_create_social_user(
        db, provider="naver", social_id=social_id,
        email=email, profile_image=profile_image,
    )

    jwt_token = create_access_token(data={"sub": str(user.id)})
    logger.info(f"Naver OAuth callback: user_id={user.id}")
    return RedirectResponse(f"{settings.FRONTEND_URL}/?token={jwt_token}")
