from pydantic import BaseModel, Field, computed_field, model_validator
from typing import Literal, Optional, List
from datetime import date, datetime

# --- Calculator Schemas ---
class BidCalculationRequest(BaseModel):
    basic_price: float = Field(gt=0)
    rate: float = Field(gt=-100, le=100)  # e.g., -5.0 for 사정률 -5%
    contract_type: Optional[str] = "CONSTRUCTION"
    a_value: Optional[int] = Field(default=0, ge=0)  # A값 (고정비용)
    # 0원은 "못 찾음"이 아니라 공고에서 비대상임을 확인한 경우만 허용한다.
    # 양수 A값은 공고/사용자 입력으로 확인된 값이어야 한다.
    # Additive compatibility: legacy manual-calculator callers that omit this
    # field are accepted only for A=0. Notice-backed clients must still send an
    # explicit provenance status and all positive A values require confirmation.
    a_value_status: Optional[Literal["confirmed", "not_applicable"]] = None
    # 용역·물품은 보편 하한율이 없으므로 공고 명시값이 있어야 계산한다.
    lower_limit_rate: Optional[float] = Field(default=None, gt=0, le=100)
    # 공사 하한율 시행일과 공고별 복수예비가격 범위를 재현하기 위한 입력.
    bid_date: Optional[date] = None
    prdprc_range_bgn: Optional[float] = Field(default=None, ge=-20, le=20)
    prdprc_range_end: Optional[float] = Field(default=None, ge=-20, le=20)

    @model_validator(mode="after")
    def validate_a_value_provenance(self):
        value = self.a_value or 0
        if value > 0 and self.a_value_status != "confirmed":
            raise ValueError("양수 A값은 a_value_status=confirmed 여야 합니다.")
        if value == 0 and self.a_value_status == "confirmed":
            raise ValueError(
                "A값 0원은 a_value_status=confirmed 로 표시할 수 없습니다."
            )
        return self

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
    estimated_price_min: Optional[float] = None
    estimated_price_max: Optional[float] = None
    
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

    # `basic_price` is the public API's presmptPrce (estimated price), not the
    # confirmed basis amount used by safety calculations.  These additive
    # fields let new clients refuse unsafe fallback while old clients keep
    # parsing the existing response.
    basis_amount: Optional[float] = None
    basis_amount_at: Optional[datetime] = None
    lower_limit_rate: Optional[float] = None
    prdprc_range_bgn: Optional[float] = None
    prdprc_range_end: Optional[float] = None
    a_value: Optional[int] = None
    a_value_source: Optional[str] = None
    a_value_applicable: Optional[str] = None
    net_cost: Optional[int] = None


class Notice(NoticeBase):
    @computed_field
    @property
    def basis_status(self) -> str:
        return "confirmed" if (self.basis_amount or 0) > 0 else "unconfirmed"

    @computed_field
    @property
    def lower_limit_source(self) -> Optional[str]:
        return "notice" if self.lower_limit_rate is not None else None

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
    basis_amount: Optional[float] = None      # bssAmt/bssamt (확정 기초금액)
    basis_status: str = "unconfirmed"        # confirmed | unconfirmed
    basis_amount_at: Optional[datetime] = None
    budget_amount: Optional[float] = None     # asignBdgtAmt (배정예산)
    organization: Optional[str] = None        # 공고기관
    demand_organization: Optional[str] = None # 수요기관
    opening_date: Optional[str] = None        # 개찰일시 (= 사실상 마감)
    bid_date: Optional[date] = None           # 공고일/입찰 규칙 시행일 판정 기준
    contract_method: Optional[str] = None     # 계약방법
    bid_method: Optional[str] = None          # 입찰방법
    qualification: Optional[str] = None       # 입찰자격 관련 텍스트 (있으면)
    region: Optional[str] = None              # prtcptLmtRgnNm (참가제한지역)
    contract_type: Optional[str] = None       # CONSTRUCTION/SERVICE/GOODS
    lower_limit_rate: Optional[float] = None  # 공고 명시값만; 임의 기본값 금지
    lower_limit_source: Optional[str] = None  # notice | table | none
    prdprc_range_bgn: Optional[float] = None
    prdprc_range_end: Optional[float] = None
    a_value: Optional[int] = None
    a_value_source: Optional[str] = None
    a_value_applicable: Optional[str] = None
    net_cost: Optional[int] = None


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
