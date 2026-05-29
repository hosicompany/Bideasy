from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.db.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=True)
    company_name = Column(String(255), default="")
    ceo_name = Column(String(100))

    # Social auth
    social_provider = Column(String(20), nullable=True)  # 'kakao' | 'naver'
    social_id = Column(String(100), nullable=True, index=True)
    profile_image_url = Column(String(500), nullable=True)

    # My Page Fields
    licenses = Column(Text)
    location = Column(String(100))
    capacity_cost = Column(Integer, default=0)
    performance_record = Column(Integer, default=0)

    points = Column(Integer, default=0)

    # Subscription
    tier = Column(String(20), default="free")  # free | pro | pro_plus
    subscription_expires_at = Column(DateTime, nullable=True)

    # 14일 Pro 체험 (신규 가입 시 자동 활성화, 만료 후 Free 다운그레이드)
    # trial_started_at != None 이면 이미 체험을 시작한 적이 있는 사용자 (재체험 불가)
    trial_started_at = Column(DateTime, nullable=True)
    trial_expires_at = Column(DateTime, nullable=True)

    # 관리자 권한 (require_admin 의존성에서 검사)
    is_admin = Column(Boolean, nullable=False, default=False, server_default="false")

    bids = relationship("UserBid", back_populates="user")
    point_transactions = relationship("PointTransaction", back_populates="user")


class Notice(Base):
    __tablename__ = "notices"

    bid_no = Column(String(100), primary_key=True, index=True)
    title = Column(String(500), index=True)
    content = Column(Text)
    basic_price = Column(Float)
    contract_type = Column(String(50), default="CONSTRUCTION")
    start_date = Column(DateTime)
    end_date = Column(DateTime)

    # Extended fields
    organization = Column(String(255))
    demand_organization = Column(String(255))
    bid_method = Column(String(100))
    contract_method = Column(String(100))
    bid_type = Column(String(100))
    status = Column(String(50))
    region = Column(String(100))
    budget_amount = Column(Float)
    opening_date = Column(String(100))
    international_bid = Column(String(10))
    joint_contract = Column(String(10))
    sme_only = Column(String(10))
    big_company_ok = Column(String(10))
    bid_qualification = Column(String(255))
    emergency_bid = Column(String(10))
    rebid_yn = Column(String(10))
    attachment_url = Column(String(500))
    attachment_name = Column(String(255))

    # Calculator Fields
    a_value = Column(Integer, default=0)
    net_cost = Column(Integer, default=0)

    # Relationships
    bids = relationship("UserBid", back_populates="notice")
    ai_log = relationship("AIAnalysisLog", back_populates="notice", uselist=False)
    favorites = relationship("Favorite", back_populates="notice")

    def to_dict(self):
        return {
            "bid_no": self.bid_no,
            "title": self.title,
            "content": self.content,
            "basic_price": self.basic_price,
            "contract_type": self.contract_type,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "organization": self.organization,
            "demand_organization": self.demand_organization,
            "bid_method": self.bid_method,
            "contract_method": self.contract_method,
            "bid_type": self.bid_type,
            "status": self.status,
            "region": self.region,
            "budget_amount": self.budget_amount,
            "opening_date": self.opening_date,
            "international_bid": self.international_bid,
            "joint_contract": self.joint_contract,
            "sme_only": self.sme_only,
            "big_company_ok": self.big_company_ok,
            "bid_qualification": self.bid_qualification,
            "emergency_bid": self.emergency_bid,
            "rebid_yn": self.rebid_yn,
            "attachment_url": self.attachment_url,
            "attachment_name": self.attachment_name,
            "a_value": self.a_value,
            "net_cost": self.net_cost,
        }


class UserBid(Base):
    __tablename__ = "user_bids"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    notice_id = Column(String(100), ForeignKey("notices.bid_no"))

    bid_price = Column(Integer)
    rate = Column(Float)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="bids")
    notice = relationship("Notice", back_populates="bids")


class OpeningResult(Base):
    __tablename__ = "opening_results"

    bid_no = Column(String(100), primary_key=True, index=True)

    organization = Column(String(255), index=True)
    region = Column(String(100), index=True)

    open_date = Column(DateTime, index=True)
    basic_price = Column(Float)
    reserved_price = Column(Float)
    bid_method = Column(String(100))

    winner_company = Column(String(255))
    winner_price = Column(Float)
    winner_rate = Column(Float)

    participants_count = Column(Integer)

    crawled_at = Column(DateTime, default=_utcnow)


class AIAnalysisLog(Base):
    __tablename__ = "ai_analysis_logs"

    bid_no = Column(String(100), ForeignKey("notices.bid_no"), primary_key=True)
    summary_json = Column(JSON)
    risk_factors = Column(JSON)
    llm_model = Column(String(50), default="gpt-4o-mini")
    token_usage = Column(Integer)
    created_at = Column(DateTime, default=_utcnow)

    notice = relationship("Notice", back_populates="ai_log")


class PointTransaction(Base):
    __tablename__ = "point_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    tx_type = Column(String(50), nullable=False)
    description = Column(String(255))
    bid_no = Column(String(100), ForeignKey("notices.bid_no"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="point_transactions")


class PaymentOrder(Base):
    __tablename__ = "payment_orders"

    id = Column(Integer, primary_key=True, index=True)
    # user_id nullable=True — SET NULL 정책 (사용자 삭제 시 회계 기록 보존)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    order_id = Column(String(64), unique=True, index=True, nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String(20), default="PENDING", index=True)  # PENDING/CONFIRMED/FAILED
    payment_key = Column(String(200), unique=True, nullable=True)
    method = Column(String(50), nullable=True)
    point_transaction_id = Column(Integer, ForeignKey("point_transactions.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    confirmed_at = Column(DateTime, nullable=True, index=True)
    fail_reason = Column(String(500), nullable=True)

    # 환불 추적 (관리자 환불 처리 시)
    refund_amount = Column(Integer, nullable=True)  # 부분 환불 누적 합
    refund_reason = Column(String(500), nullable=True)
    refunded_at = Column(DateTime, nullable=True)  # idempotency 검사 키
    refund_payment_key = Column(String(200), nullable=True)  # Toss 환불 응답

    # 캠페인 할인 (예: 첫 달 50% 자동 win-back)
    # amount + discount_amount = 정가. discount_reason 으로 효과 분석.
    discount_amount = Column(Integer, nullable=True)
    discount_reason = Column(String(50), nullable=True)  # 예: TRIAL_WINBACK_50

    user = relationship("User")


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    bid_no = Column(String(100), ForeignKey("notices.bid_no"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    notice = relationship("Notice", back_populates="favorites")


class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    fcm_token = Column(String(500), nullable=False, index=True)
    device_type = Column(String(20), nullable=False)  # android | ios | web
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user = relationship("User")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(String(1000), nullable=False)
    noti_type = Column(String(50), nullable=False)  # new_bid | favorite_update | subscription_expiry
    data_json = Column(JSON, nullable=True)  # extra payload (bid_no, etc.)
    is_read = Column(Integer, default=0)  # 0=unread, 1=read
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User")
