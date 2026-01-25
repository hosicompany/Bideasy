from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# --- Calculator Schemas ---
class BidCalculationRequest(BaseModel):
    basic_price: float
    rate: float # e.g., 1.25 for +1.25%

class BidCalculationResponse(BaseModel):
    original_price: float
    rate: float
    result_price: int
    is_safe: bool
    warning_message: Optional[str] = None

# --- Notice Schemas ---
class NoticeBase(BaseModel):
    bid_no: str
    title: str
    basic_price: float
    content: Optional[str] = None # Link URL
    contract_type: Optional[str] = "CONSTRUCTION"
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

class Notice(NoticeBase):
    class Config:
        from_attributes = True


# --- User Bid Schemas ---
class UserBidCreate(BaseModel):
    notice_id: str
    bid_price: int
    rate: float

class UserBid(UserBidCreate):
    id: int
    user_id: int
    
    class Config:
        from_attributes = True

# --- AI Analysis Schemas ---
class RiskFactor(BaseModel):
    type: str # e.g., "Term", "Penalty"
    content: str
    level: str # HIGH, MEDIUM, LOW

class BidAnalysisResponse(BaseModel):
    summary: List[str]
    risks: List[RiskFactor]
