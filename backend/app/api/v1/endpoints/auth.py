from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import httpx

from app.core.rate_limit import limiter
from app.db.session import get_db
from app.db import models
from app.schemas import user as user_schemas
from app.schemas.point import SIGNUP_BONUS
from app.schemas.subscription import activate_trial
from app.core.security import (
    verify_password,
    get_password_hash,
    create_token_for_user,
    create_oauth_state,
    verify_oauth_state,
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
    email_verified: bool = False,
) -> models.User:
    """Find existing user by social identity, email, or create new one.

    보안: 이메일로 기존 계정에 소셜 식별자를 병합(계정 연결)하는 것은 공급자가
    이메일 소유를 검증(email_verified=True)한 경우에만 허용한다. 미검증 이메일로
    타인의 기존 계정(비밀번호 가입)을 탈취하는 경로를 차단한다.
    """
    user = db.query(models.User).filter(
        models.User.social_provider == provider,
        models.User.social_id == social_id,
    ).first()

    if not user and email and email_verified:
        existing = db.query(models.User).filter(models.User.email == email).first()
        if existing:
            existing.social_provider = provider
            existing.social_id = social_id
            if profile_image:
                existing.profile_image_url = profile_image
            user = existing

    if not user:
        # 새 계정 생성. 단, 미검증 이메일이 기존 계정과 충돌하면 이메일 없이 생성
        # (미검증 이메일로 기존 계정과 같은 이메일을 차지해 혼동/탈취되는 것 방지).
        email_for_new = email
        if email and not email_verified:
            conflict = db.query(models.User).filter(models.User.email == email).first()
            if conflict:
                email_for_new = None
        user = models.User(
            email=email_for_new,
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
        # 신규 가입자에게 14일 Pro 체험 자동 부여
        activate_trial(user)
        logger.info(f"Trial activated: user_id={user.id}, expires={user.trial_expires_at}")

    db.commit()
    db.refresh(user)
    return user


@router.post("/register", response_model=user_schemas.UserResponse)
@limiter.limit("5/minute")
def register(request: Request, user_in: user_schemas.UserCreate, db: Session = Depends(get_db)):
    """회원가입 — IP당 분당 5회로 제한(계정 대량 생성·이메일 열거 어뷰징 완화)."""
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
    # 신규 가입자에게 14일 Pro 체험 자동 부여
    activate_trial(user)
    logger.info(f"Trial activated: user_id={user.id}, expires={user.trial_expires_at}")

    db.commit()
    db.refresh(user)
    return user


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """로그인 (JWT 토큰 발급) — IP당 분당 10회로 제한(브루트포스 완화, nginx 보강)."""
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not user.hashed_password or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_token_for_user(user)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/social")
@limiter.limit("10/minute")
async def social_login(
    request: Request,
    payload: user_schemas.SocialLoginRequest,
    db: Session = Depends(get_db),
):
    """카카오/네이버 소셜 로그인 (모바일 SDK용 - access_token 직접 전달)"""
    social_id = None
    email = None
    profile_image = None
    email_verified = False

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
            # 카카오는 이메일 검증 여부를 명시적으로 제공
            email_verified = bool(email) and kakao_account.get("is_email_verified") is True
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
            # 네이버 계정 이메일은 가입 시 검증됨
            email_verified = bool(email)
            profile_image = data.get("profile_image")

        else:
            raise HTTPException(status_code=400, detail="지원하지 않는 소셜 로그인이에요")

    user = _find_or_create_social_user(
        db, provider=payload.provider, social_id=social_id,
        email=email, profile_image=profile_image, email_verified=email_verified,
    )

    access_token = create_token_for_user(user)
    logger.info(f"Social login: provider={payload.provider}, user_id={user.id}")
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/social-urls")
def get_social_login_urls():
    """OAuth 인가 URL 반환 (프론트엔드에서 호출)"""
    # CSRF 방어: 서명된 state 를 발급하고 콜백에서 검증 (카카오·네이버 모두)
    kakao_state = create_oauth_state()
    naver_state = create_oauth_state()
    base = f"{settings.BACKEND_URL}{settings.API_V1_STR}"
    kakao_cb = f"{base}/auth/callback/kakao"
    naver_cb = f"{base}/auth/callback/naver"

    return {
        "kakao": (
            f"https://kauth.kakao.com/oauth/authorize"
            f"?client_id={settings.KAKAO_REST_API_KEY}"
            f"&redirect_uri={kakao_cb}"
            f"&response_type=code"
            f"&state={kakao_state}"
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
async def kakao_callback(code: str, state: str = "", db: Session = Depends(get_db)):
    """카카오 OAuth 콜백 - 인가 코드 → JWT → 프론트엔드 리다이렉트"""
    # CSRF 방어: 서버가 발급한 서명 state 인지 검증
    if not verify_oauth_state(state):
        logger.warning("Kakao callback: invalid/expired oauth state")
        return RedirectResponse(f"{settings.FRONTEND_URL}/?error=invalid_state")
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
    email_verified = bool(email) and kakao_account.get("is_email_verified") is True
    profile_image = kakao_account.get("profile", {}).get("thumbnail_image_url")

    user = _find_or_create_social_user(
        db, provider="kakao", social_id=social_id,
        email=email, profile_image=profile_image, email_verified=email_verified,
    )

    jwt_token = create_token_for_user(user)
    logger.info(f"Kakao OAuth callback: user_id={user.id}")
    # 토큰을 URL fragment 로 전달 — 쿼리스트링과 달리 서버 액세스로그·Referer 에 남지 않음
    return RedirectResponse(f"{settings.FRONTEND_URL}/#token={jwt_token}")


@router.get("/callback/naver")
async def naver_callback(code: str, state: str, db: Session = Depends(get_db)):
    """네이버 OAuth 콜백 - 인가 코드 → JWT → 프론트엔드 리다이렉트"""
    # CSRF 방어: 서버가 발급한 서명 state 인지 검증
    if not verify_oauth_state(state):
        logger.warning("Naver callback: invalid/expired oauth state")
        return RedirectResponse(f"{settings.FRONTEND_URL}/?error=invalid_state")
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
    email_verified = bool(email)  # 네이버 계정 이메일은 가입 시 검증됨
    profile_image = naver_data.get("profile_image")

    user = _find_or_create_social_user(
        db, provider="naver", social_id=social_id,
        email=email, profile_image=profile_image, email_verified=email_verified,
    )

    jwt_token = create_token_for_user(user)
    logger.info(f"Naver OAuth callback: user_id={user.id}")
    # 토큰을 URL fragment 로 전달 — 쿼리스트링과 달리 서버 액세스로그·Referer 에 남지 않음
    return RedirectResponse(f"{settings.FRONTEND_URL}/#token={jwt_token}")
