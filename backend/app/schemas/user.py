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
    subscription_expires_at: Optional[str] = None
    social_provider: Optional[str] = None
    profile_image_url: Optional[str] = None

    class Config:
        from_attributes = True


class SocialLoginRequest(BaseModel):
    provider: str       # 'kakao' | 'naver'
    access_token: str   # social SDK token
