from datetime import datetime
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class UserBase(BaseModel):
    company_name: Optional[str] = None
    ceo_name: Optional[str] = None
    licenses: Optional[str] = None # JSON string or comma-separated
    location: Optional[str] = None
    capacity_cost: Optional[int] = 0
    performance_record: Optional[int] = 0

class UserCreate(UserBase):
    # 형식 검증된 이메일 + 최소 8자 비밀번호 (비밀번호 변경 정책과 일치)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    # 유입 귀속(선택) — 프론트 first-touch 캡처에서 전달, 가입 시 User 에 저장.
    # 길이 제한은 두지 않고(긴 referrer URL 이 가입을 막지 않도록) 서버에서 컬럼 길이로 절단.
    signup_source: Optional[str] = None
    signup_medium: Optional[str] = None
    signup_campaign: Optional[str] = None
    signup_referrer: Optional[str] = None

class UserUpdate(UserBase):
    pass

class UserResponse(UserBase):
    id: int
    email: Optional[str] = None
    points: int
    tier: str = "free"
    # Optional[str] 였으나 SQLAlchemy 모델은 datetime 을 반환 → Pydantic V2 가 자동
    # 캐스팅 안 함 → ResponseValidationError 발생했음. datetime 으로 정정.
    # FastAPI JSON 응답에서는 자동으로 ISO 8601 문자열로 직렬화된다.
    subscription_expires_at: Optional[datetime] = None
    trial_started_at: Optional[datetime] = None
    trial_expires_at: Optional[datetime] = None
    is_admin: bool = False
    social_provider: Optional[str] = None
    profile_image_url: Optional[str] = None

    class Config:
        from_attributes = True


class SocialLoginRequest(BaseModel):
    provider: str       # 'kakao' | 'naver'
    access_token: str   # social SDK token


class PasswordChange(BaseModel):
    current_password: str
    new_password: str
