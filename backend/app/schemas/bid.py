from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# --- Calculator Schemas ---
class BidCalculationRequest(BaseModel):
    basic_price: float
    rate: float  # e.g., -5.0 for 사정률 -5%
    contract_type: Optional[str] = "CONSTRUCTION"
    a_value: Optional[int] = 0  # A값 (고정비용)

class BidCalculationResponse(BaseModel):
    original_price: float
    rate: float
    result_price: int
    is_safe: bool
    warning_message: Optional[str] = None


class DetailedBidCalculationResponse(BaseModel):
    """상세 투찰가 계산 결과"""
    original_price: float           # 기초금액
    rate: float                     # 사정률 (%)
    result_price: int               # 투찰금액 (1원 절사)
    
    # 예정가격 정보
    estimated_price_min: float      # 예정가격 최소 (기초금액 -3%)
    estimated_price_max: float      # 예정가격 최대 (기초금액 +3%)
    
    # 하한선 정보
    lower_limit_rate: float         # 낙찰하한율 (%)
    lower_limit_price: int          # 낙찰하한선 금액
    
    # A값 정보
    a_value: int = 0                # A값 (고정비용)
    a_value_applied: bool = False   # A값 적용 여부
    
    # 안전도
    safety_level: str               # SAFE, WARNING, DANGER
    distance_from_limit: float      # 하한선 대비 여유율 (%)
    
    # 메시지
    warning_message: Optional[str] = None
    
    # 포맷된 문자열 (UI용)
    result_price_formatted: str
    lower_limit_formatted: str
    a_value_formatted: Optional[str] = None



# --- Notice Schemas ---
class NoticeBase(BaseModel):
    bid_no: str
    title: str
    basic_price: float
    content: Optional[str] = None  # Link URL
    contract_type: Optional[str] = "CONSTRUCTION"
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    organization: Optional[str] = None  # 발주처
    
    # Extended fields from Public Data Portal API
    demand_organization: Optional[str] = None  # 수요기관
    bid_method: Optional[str] = None  # 입찰방식
    contract_method: Optional[str] = None  # 계약방법
    region: Optional[str] = None  # 지역
    budget_amount: Optional[float] = None  # 추정가격
    opening_date: Optional[str] = None  # 개찰일시
    international_bid: Optional[str] = None  # 국제입찰여부
    joint_contract: Optional[str] = None  # 공동계약여부
    big_company_ok: Optional[str] = None  # 대기업참가허용여부
    sme_only: Optional[str] = None  # 중소기업제한여부
    bid_qualification: Optional[str] = None  # 입찰자격
    emergency_bid: Optional[str] = None  # 긴급입찰여부
    rebid_yn: Optional[str] = None  # 재입찰여부
    attachment_url: Optional[str] = None  # 첨부파일 URL
    attachment_name: Optional[str] = None  # 첨부파일명


class Notice(NoticeBase):
    class Config:
        from_attributes = True


# --- Bid Context Schemas (DOM 의존도 축소 리팩터) ---
# OpenAPI/DB 에서 가져오는 공고 본문 필드. A값은 OpenAPI 에 없으므로(판정 C)
# 이 스키마에 a_value 필드를 두지 않는다 — A값은 익스텐션이 DOM 에서 추출.
class BidContextResponse(BaseModel):
    bid_ntce_no: str
    found: bool                       # OpenAPI/DB 에서 찾았는지 (false → 익스텐션 DOM fallback)
    source: str                       # "cache" | "api" | "none"
    title: Optional[str] = None
    estimated_price: Optional[float] = None   # presmptPrce (추정가격)
    budget_amount: Optional[float] = None     # asignBdgtAmt (배정예산)
    organization: Optional[str] = None        # 공고기관
    demand_organization: Optional[str] = None # 수요기관
    opening_date: Optional[str] = None        # 개찰일시 (= 사실상 마감)
    contract_method: Optional[str] = None     # 계약방법
    bid_method: Optional[str] = None          # 입찰방법
    qualification: Optional[str] = None       # 입찰자격 관련 텍스트 (있으면)
    region: Optional[str] = None              # prtcptLmtRgnNm (참가제한지역)
    contract_type: Optional[str] = None       # CONSTRUCTION/SERVICE/GOODS


class BatchContextRequest(BaseModel):
    bid_ntce_nos: List[str]


# 목록 자격뱃지용 최소 필드. 면허는 OpenAPI 에 전용 필드가 없으므로
# title 정규식으로 복원 가능하도록 title 도 함께 반환.
class BatchContextItem(BaseModel):
    bid_ntce_no: str
    found: bool
    title: Optional[str] = None
    region: Optional[str] = None          # 자격매칭 핵심 (prtcptLmtRgnNm)
    contract_type: Optional[str] = None   # 카테고리 힌트
    qualification: Optional[str] = None


class BatchContextResponse(BaseModel):
    items: List[BatchContextItem]
    found_count: int
    miss_count: int


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


class OpeningResult(BaseModel):
    rank: int
    company: str
    ceo: str
    bid_price: float
    bid_rate: float
    success_state: str
    note: str

class BidAnalysisResponse(BaseModel):
    summary: List[str]
    risks: List[RiskFactor]
