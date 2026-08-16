import re
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.db.session import get_db
from app.db import models
from app.schemas import user as user_schemas
from app.schemas.point import SIGNUP_BONUS
from app.schemas.subscription import activate_trial
from app.services import consent as consent_service
from app.services.activation import record_profile_completed
from app.services.lead_conversion import link_leads_to_user
from app.core.security import (
    verify_password,
    get_password_hash,
    create_token_for_user,
    create_oauth_state,
    decode_oauth_state,
)
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

KAKAO_USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"
NAVER_USER_INFO_URL = "https://openapi.naver.com/v1/nid/me"

router = APIRouter()
_ATTRIBUTION_VALUE_RE = re.compile(r"^[0-9A-Za-z가-힣._:-]+$")


def _validated_signup_attribution(
    db: Session,
    *,
    source: str | None = None,
    medium: str | None = None,
    campaign: str | None = None,
    content: str | None = None,
    creative_id: str | None = None,
) -> dict[str, str]:
    """OAuth state에 넣어도 되는 비민감 first-touch 좌표만 정규화한다."""

    def clean(value: str | None, limit: int) -> str | None:
        normalized = (value or "").strip()
        if not normalized or len(normalized) > limit:
            return None
        if not _ATTRIBUTION_VALUE_RE.fullmatch(normalized):
            return None
        return normalized

    attribution = {
        "source": clean(source, 120),
        "medium": clean(medium, 120),
        "campaign": clean(campaign, 160),
        "content": clean(content, 160),
    }
    candidate_creative_id = clean(creative_id, 36)
    if candidate_creative_id and db.query(models.CreativeBrief.id).filter(
        models.CreativeBrief.id == candidate_creative_id,
        models.CreativeBrief.status.in_(("APPROVED", "PUBLISHED")),
    ).first():
        attribution["creative_id"] = candidate_creative_id
    return {key: value for key, value in attribution.items() if value}


def _attribution_from_state(db: Session, payload: dict) -> dict[str, str]:
    raw = payload.get("attribution")
    if not isinstance(raw, dict):
        return {}
    return _validated_signup_attribution(
        db,
        source=raw.get("source"),
        medium=raw.get("medium"),
        campaign=raw.get("campaign"),
        content=raw.get("content"),
        creative_id=raw.get("creative_id"),
    )


def _find_or_create_social_user(
    db: Session,
    provider: str,
    social_id: str,
    email: str | None,
    profile_image: str | None,
    email_verified: bool = False,
    attribution: dict[str, str] | None = None,
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

    created = False
    if not user:
        # 새 계정 생성. 단, 미검증 이메일이 기존 계정과 충돌하면 이메일 없이 생성
        # (미검증 이메일로 기존 계정과 같은 이메일을 차지해 혼동/탈취되는 것 방지).
        created = True
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
            signup_source=(attribution or {}).get("source"),
            signup_medium=(attribution or {}).get("medium"),
            signup_campaign=(attribution or {}).get("campaign"),
            signup_content=(attribution or {}).get("content"),
            signup_creative_id=(attribution or {}).get("creative_id"),
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
    # 신규 소셜 가입만 리드 전환 링크 (기존 계정 로그인은 스킵). best-effort 백스톱 —
    # 링크가 어떤 이유로든 터져도 가입은 이미 커밋됐으므로 절대 실패시키지 않는다.
    if created:
        try:
            link_leads_to_user(db, user)
        except Exception:
            logger.exception("lead linking backstop (social) user_id=%s", user.id)
        # 체험 시작 안내는 거래라 소셜 가입자도 받는다(만료 고지도 마찬가지).
        # 다만 소셜 가입 폼에는 광고 수신 동의 UI 가 없으므로 **광고 3종(D1/D3/D7)의
        # 대상은 되지 않는다** — 동의를 받은 적이 없으니 그게 맞다.
        _send_trial_welcome(db, user)
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

    signup_creative_id = (user_in.signup_creative_id or "").strip()[:36] or None
    if signup_creative_id and not db.query(models.CreativeBrief.id).filter(
        models.CreativeBrief.id == signup_creative_id,
        models.CreativeBrief.status.in_(("APPROVED", "PUBLISHED")),
    ).first():
        signup_creative_id = None

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
        # 유입 귀속 — 컬럼 길이로 안전 절단, 빈 문자열은 None 으로 정규화
        signup_source=(user_in.signup_source or "")[:120] or None,
        signup_medium=(user_in.signup_medium or "")[:120] or None,
        signup_campaign=(user_in.signup_campaign or "")[:160] or None,
        signup_content=(user_in.signup_content or "")[:160] or None,
        signup_creative_id=signup_creative_id,
        signup_referrer=(user_in.signup_referrer or "")[:300] or None,
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

    # 활성화 계측: 가입 폼에서 면허·소재지를 함께 채워 온 경우 — PUT /users/me 를
    # 거치지 않으므로 여기서도 기록해야 한다 (아래 commit 에 편승).
    record_profile_completed(user)

    # 광고성 정보 수신 동의(선택) — 동의한 경우에만 상태+증적 기록.
    # 미동의는 정상 경로다(거래 관련 안내는 동의와 무관하게 나감).
    optin_pending = False
    if user_in.marketing_consent:
        try:
            # confirmed=False — 이 폼도 이메일 소유를 확인하지 않는다. 남의 주소로
            # 가입하면서 체크박스를 켜면 그 주소로 광고가 나가게 되므로, 리드 캡처와
            # 동일하게 주소 소유자가 확인 링크를 누를 때까지 발송 대상에서 뺀다.
            # (소셜 로그인은 제공자가 email_verified 를 주므로 이 경로가 아니다.)
            consent_service.grant_marketing(
                db, user, subject_type="user", source="web_signup",
                channel="email",
                version=(user_in.consent_version or consent_service.SIGNUP_MARKETING_VERSION),
                request=request,
                confirmed=False,
            )
            optin_pending = True
        except consent_service.UnknownConsentVersion:
            # 캐시된 구버전 폼 — 가입 자체는 막지 않고 미동의로 남긴다(임의 기록 금지).
            logger.warning("signup marketing consent: unknown text version %s", user_in.consent_version)

    db.commit()
    db.refresh(user)

    # 가입 응답 경로에서 나가는 메일은 **항상 1통**이다. 여기는 퍼널의 목이라 외부
    # I/O 를 최소로 둔다 — SES 가 한 번 느려지면 가입 자체가 504 로 실패하고, 계정은
    # 이미 커밋돼 있어 재시도하면 "이미 등록된 이메일"이 되는 사각지대가 생긴다.
    # 동의자는 확인 메일만 받고, 웰컴은 확인 클릭 직후에 보낸다(optin.py).
    if optin_pending:
        _send_optin_confirm(db, user)
    else:
        _send_trial_welcome(db, user)
    # 리드 전환 링크 — 동일 이메일 진단 리드가 있으면 converted 기록. best-effort 백스톱.
    try:
        link_leads_to_user(db, user)
    except Exception:
        logger.exception("lead linking backstop (register) user_id=%s", user.id)
    return user


def _send_trial_welcome(db, user) -> None:
    """D0 — 체험 시작 안내(거래). 동의와 무관하게 전원에게 나간다.

    거래성인 이유는 방금 시작한 서비스의 **이용 안내**이기 때문이다. 프로필이 비어 있으면
    자격 판정이 '판정 불가'로 나오므로 그 사실을 알리는 건 기능 설명이지 광고가 아니다.
    할인·구매 권유를 넣는 순간 광고가 되므로 템플릿에 넣지 않았다.
    """
    from app.schemas.subscription import TRIAL_DAYS
    from app.services import nurture

    if not user.email:
        return
    needs_profile = not (user.licenses or "").strip() and not (user.location or "").strip()
    try:
        nurture.send_transactional(
            db, user,
            subject_type="user",
            template="trial_welcome",
            ctx={"trial_days": TRIAL_DAYS, "needs_profile": needs_profile},
            dedupe_key=f"trial_welcome:user:{user.id}",
        )
    except Exception as e:  # noqa: BLE001 — 가입 응답을 절대 막지 않는다
        db.rollback()
        logger.warning("trial welcome 발송 실패(비치명적) user=%s: %s", user.id, e)


def _send_optin_confirm(db, user) -> None:
    """가입 시 수신동의한 회원에게 확인 메일 — best-effort.

    회원은 이미 커밋됐다. 발송이 실패해도 **가입을 되돌리지 않는다** — 확인 메일 한 통
    때문에 가입 자체를 잃는 것이 훨씬 큰 손해다. 확인 전까지는 `sendable_filter` 가
    광고를 막으므로, 실패해도 위법 발송으로는 이어지지 않는다.

    이 메일은 광고가 아니라 거래성(확인 요청)이라 미확인 주소에도 보낼 수 있다.
    """
    from app.services import nurture

    if not user.email:
        return
    try:
        nurture.send_transactional(
            db, user,
            subject_type="user",
            template="signup_optin_confirm",
            ctx={"confirm_url": nurture.optin_url("user", user.id)},
            dedupe_key=f"signup_optin_confirm:user:{user.id}",
        )
    except Exception as e:  # noqa: BLE001 — 가입 응답을 절대 막지 않는다
        db.rollback()
        logger.warning("signup optin 확인메일 발송 실패(비치명적) user=%s: %s", user.id, e)


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
        attribution=_validated_signup_attribution(
            db,
            source=payload.signup_source,
            medium=payload.signup_medium,
            campaign=payload.signup_campaign,
            content=payload.signup_content,
            creative_id=payload.signup_creative_id,
        ),
    )

    access_token = create_token_for_user(user)
    logger.info(f"Social login: provider={payload.provider}, user_id={user.id}")
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/social-urls")
def get_social_login_urls(
    signup_source: str | None = None,
    signup_medium: str | None = None,
    signup_campaign: str | None = None,
    signup_content: str | None = None,
    signup_creative_id: str | None = None,
    db: Session = Depends(get_db),
):
    """OAuth 인가 URL 반환 (프론트엔드에서 호출)"""
    # CSRF 방어: 서명된 state 를 발급하고 콜백에서 검증 (카카오·네이버 모두)
    attribution = _validated_signup_attribution(
        db,
        source=signup_source,
        medium=signup_medium,
        campaign=signup_campaign,
        content=signup_content,
        creative_id=signup_creative_id,
    )
    kakao_state = create_oauth_state(attribution=attribution)
    naver_state = create_oauth_state(attribution=attribution)
    base = f"{settings.BACKEND_URL}{settings.API_V1_STR}"
    kakao_cb = f"{base}/auth/callback/kakao"
    naver_cb = f"{base}/auth/callback/naver"

    return {
        "kakao": "https://kauth.kakao.com/oauth/authorize?" + urlencode(
            {
                "client_id": settings.KAKAO_REST_API_KEY,
                "redirect_uri": kakao_cb,
                "response_type": "code",
                "state": kakao_state,
            }
        ),
        "naver": "https://nid.naver.com/oauth2.0/authorize?" + urlencode(
            {
                "client_id": settings.NAVER_CLIENT_ID,
                "redirect_uri": naver_cb,
                "response_type": "code",
                "state": naver_state,
            }
        ),
    }


@router.get("/callback/kakao")
async def kakao_callback(code: str, state: str = "", db: Session = Depends(get_db)):
    """카카오 OAuth 콜백 - 인가 코드 → JWT → 프론트엔드 리다이렉트"""
    # CSRF 방어: 서버가 발급한 서명 state 인지 검증
    state_payload = decode_oauth_state(state)
    if state_payload is None:
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
        attribution=_attribution_from_state(db, state_payload),
    )

    jwt_token = create_token_for_user(user)
    logger.info(f"Kakao OAuth callback: user_id={user.id}")
    # 토큰을 URL fragment 로 전달 — 쿼리스트링과 달리 서버 액세스로그·Referer 에 남지 않음
    return RedirectResponse(f"{settings.FRONTEND_URL}/#token={jwt_token}")


@router.get("/callback/naver")
async def naver_callback(code: str, state: str, db: Session = Depends(get_db)):
    """네이버 OAuth 콜백 - 인가 코드 → JWT → 프론트엔드 리다이렉트"""
    # CSRF 방어: 서버가 발급한 서명 state 인지 검증
    state_payload = decode_oauth_state(state)
    if state_payload is None:
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
        attribution=_attribution_from_state(db, state_payload),
    )

    jwt_token = create_token_for_user(user)
    logger.info(f"Naver OAuth callback: user_id={user.id}")
    # 토큰을 URL fragment 로 전달 — 쿼리스트링과 달리 서버 액세스로그·Referer 에 남지 않음
    return RedirectResponse(f"{settings.FRONTEND_URL}/#token={jwt_token}")
