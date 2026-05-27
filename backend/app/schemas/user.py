from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class UserBase(BaseModel):
    company_name: Optional[str] = None
    ceo_name: Optional[str] = None
    licenses: Optional[str] = None # JSON string or comma-separated
    location: Optional[str] = None
    capacity_cost: Optional[int] = 0
    performance_record: Optional[int] = 0

class UserCreate(UserBase):
    email: str
    password: str

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
    social_provider: Optional[str] = None
    profile_image_url: Optional[str] = None

    class Config:
        from_attributes = True


class SocialLoginRequest(BaseModel):
    provider: str       # 'kakao' | 'naver'
    access_token: str   # social SDK token
