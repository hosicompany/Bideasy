from pydantic import BaseModel
from typing import Optional, List

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
    email: str
    points: int
    
    class Config:
        from_attributes = True
